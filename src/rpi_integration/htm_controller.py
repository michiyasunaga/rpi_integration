#!/usr/bin/env python

import os
import threading
import time
import re
from random import shuffle
from threading import Lock

from svox_tts.srv import Speech, SpeechRequest
from task_models.json_to_htm import json_to_htm
from task_models.task import HierarchicalTask

import rospy
from human_robot_collaboration.controller import BaseController
from human_robot_collaboration.service_request import finished_request
from ros_speech2text.msg import transcript
from rpi_integration.learner_utils import RESTUtils, parse_action
from std_msgs.msg import String


class HTMController(BaseController, RESTUtils):
    """Controls Baxter using HTN derived from json"""

    strt_time = time.time()

    BRING = 'get_pass'
    HOLD_TOP = 'hold_top'
    HOLD_LEG ='hold_leg'

    OBJECT_DICT = {
        "GET(seat)":                (   BRING, BaseController.LEFT, 198),
        "GET(back)":                (   BRING, BaseController.LEFT, 201),
        "GET(dowel)":              [(   BRING, BaseController.LEFT, 150),
                                    (   BRING, BaseController.LEFT, 151),
                                    (   BRING, BaseController.LEFT, 152),
                                    (   BRING, BaseController.LEFT, 153),
                                    (   BRING, BaseController.LEFT, 154),
                                    (   BRING, BaseController.LEFT, 155)],
        "GET(dowel-top)":           (   BRING, BaseController.LEFT, 156),
        "GET(FOOT_BRACKET)":       [(   BRING, BaseController.RIGHT, 10),
                                    (   BRING, BaseController.RIGHT, 11),
                                    (   BRING, BaseController.RIGHT, 12),
                                    (   BRING, BaseController.RIGHT, 13)],
        "GET(bracket-front)":      [(   BRING, BaseController.RIGHT, 14),
                                    (   BRING, BaseController.RIGHT, 15),
                                    (   BRING, BaseController.RIGHT, 22),
                                    (   BRING, BaseController.RIGHT, 23)],
        "GET(bracket-top)":        [(   BRING, BaseController.RIGHT, 16),
                                    (   BRING, BaseController.RIGHT, 17)],
        "GET(bracket-back-right)":  (   BRING, BaseController.RIGHT, 18),
        "GET(bracket-back-left)":   (   BRING, BaseController.RIGHT, 19),
        "GET(screwdriver)":         (   BRING, BaseController.RIGHT, 20),
        "HOLD(dowel)":              (HOLD_LEG, BaseController.RIGHT,  0),
        "HOLD(seat)":               (HOLD_LEG, BaseController.RIGHT,  0),
        "HOLD(back)":               (HOLD_LEG, BaseController.RIGHT,  0)

    }

    def __init__(self):
        self.param_prefix       = "/rpi_integration"
        self.json_path          = rospy.get_param(self.param_prefix + '/json_file')

        self.autostart          = rospy.get_param(self.param_prefix + '/autostart')
        self.use_stt            = rospy.get_param(self.param_prefix + '/use_stt')

        self.top_down_queries   = rospy.get_param(self.param_prefix + '/top_down')
        self.bottom_up_queries  = rospy.get_param(self.param_prefix + '/bottom_up')
        self.horizontal_queries = rospy.get_param(self.param_prefix + '/horizontal')
        self.stationary_queries = rospy.get_param(self.param_prefix + '/stationary')

        self.htm                = json_to_htm(self.json_path)
        self.last_r             = finished_request

        self.do_query           = rospy.get_param(self.param_prefix + "/do_query", False)
        self._learner_pub       = rospy.Publisher('web_interface/json',
                                                  String, queue_size =10)
        self._listen_sub        = rospy.Subscriber(self.LISTEN_TOPIC,
                                                   transcript, self._listen_query_cb)

        self.why_query_timer    = None
        self.WHY_ELAPSED_TIME   = 5.0

        self.lock               = Lock()
        self.START_CMD          = False
        self.LISTENING          = False

        BaseController.__init__(
            self,
            left=True,
            right=True,
            speech=True,
            listen=False,
            recovery=True,
        )
        RESTUtils.__init__(self)


        # self.delete()
        # self._train_learner_from_file()
        rospy.loginfo('Ready!')

    @property
    def robot_actions(self):
        return self._get_actions(self.htm.root)

    def _take_actions(self, actions):
        prev_arm      = None # was left or right arm used previously?
        same_arm      = True # Was previous action taken
                             # using the same arm as curr action?
        prev_same_arm = True # Was the previous previous
                             # action taken using same arm?

        # Publishing the htm before anything
        self._learner_pub.publish(open(self.json_path, 'r').read())

        for action in actions:

            spoken_flag = False
            while(self.LISTENING):
                if not spoken_flag:
                    rospy.loginfo("Waiting until query is done....")
                    spoken_flag = True
                rospy.sleep(0.1)


            # From the name we can get correct ROS service
            cmd, arm, obj = parse_action(action.name, self.OBJECT_DICT)
            arm_str       = "LEFT" if arm == 0 else 'RIGHT'

            prev_same_arm = same_arm == prev_same_arm
            same_arm      = True if prev_arm == None else prev_arm == arm

            self.curr_action = action

            rospy.loginfo("same arm {}, last same arm {}".format(same_arm,
                                                                 prev_same_arm))

            # Only sleep when encountering diff arms for first time.
            # prevents both arms from acting simultaneously.
            if  not same_arm and prev_same_arm:
                rospy.sleep(7)

            elapsed_time = time.time() - self.strt_time
            rospy.loginfo(
                "Taking action {} on object {} with {} arm at time {}".format(cmd,
                                                                              obj,
                                                                              arm_str,
                                                                              elapsed_time))
            # Send action to the robot
            self._action(arm, (cmd, [obj]), {'wait': False})

            elapsed_time = time.time() - self.strt_time
            rospy.loginfo(
                "Took action {} on object {} with {} arm at time {}".format(cmd,
                                                                            obj,
                                                                            arm_str,
                                                                            elapsed_time))
            prev_arm = arm


    def _get_queried_htm(self):
        cmd1 = '[["u", "We will build the back first."]]'
        cmd2 = '[["u", "We will build the screwdriver first."]]'

        self._learner_pub.publish(self.get().text)
        if self.listen_sub.wait_for_msg(timeout=20.):
            rospy.loginfo("Received do_query command...")
            self.query(cmd1)
            rospy.loginfo("Query 1 result: {}".format(self.get().text))
            self.query(cmd2)
            rospy.loginfo("Query 2 result: {}".format(self.get().text))
            self._learner_pub.publish(self.get().text)
            htm = _learner_to_htm()
            return htm

    def _run(self):
        rospy.loginfo('Starting autonomous control')
        # rospy.sleep(3) # Add a little delay for self-filming!
        if self.autostart:
            self._take_actions(self.robot_actions)
        else:
            spoken_flag = False
            while(not self.START_CMD):
                if not spoken_flag:
                    rospy.loginfo("Waiting to start....")
                    spoken_flag = True
                rospy.sleep(0.1)

            self._take_actions(self.robot_actions)

    def _get_actions(self, root):
        """ Recursively retrieves actions in correct order """
        name = root.name
        kind = root.kind # we're not evil

        try:
            children = root.children
            # If parallel, then permute the action orders
            if kind == 'Parallel':
                shuffle(children)

            # loop through all children and get their actions
            for child in children:
                for c in self._get_actions(child):
                    yield c
        except ValueError:
            if root.action.agent == 'robot':
                yield root

    def _train_learner_from_file(self):
        with open(self.CHAIR_PATH, 'r') as i:
            self.learn(i)

    def _learner_to_htm(self):
        j = json.loads(get().text)
        return HierarchicalTask(build_htm_recursively(j['nodes']))


    def _listen_query_cb(self, msg):
        rospy.loginfo("QUERY RECEIVED: {}".format(msg.transcript))
        with self.lock:
            self.LISTENING = True

        if not self.START_CMD:
            self._baxter_begin(msg.transcript.lower().strip())
            self.LISTENING = False
            return

        responses = self._select_query(msg.transcript.lower().strip())
        for response in responses:
            if self.use_stt:
                utterance        = SpeechRequest()
                utterance.mode   = utterance.SAY
                utterance.string = response

                self.speech(utterance)
            else:
                rospy.loginfo(utterance)

        with self.lock:
            self.LISTENING = False

    def _select_query(self, transcript):
        """Parses utterance to determine type of query"""
        responses        = []
        split_transcript = transcript.split()

        if len(split_transcript) > 1:
            transcript = ' '.join(split_transcript[:-1])
            param      = split_transcript[-1]


        if transcript in '\t'.join(self.top_down_queries):
            if "how can we build a" in transcript:
                task           = self.htm.find_node_by_name(self.htm.root, param)
                children_names = [c.name for c in task.children]
                response       = "In order to  {}".format(task.name)
            else:
                task           = self.htm.root.children[0]
                children_names = [c.name for c in task.children]
                response       = "Our task is to {}".format(task.name)

            responses.append(response)

            if len(children_names) > 1:
                response = "First, we will {}".format(children_names.pop())
                responses.append(response)

                while(len(children_names) > 1):
                    response = "Then, we will {}".format(children_names.pop())
                    responses.append(response)

                response = "Finally, we will {}".format(children_names.pop())
                responses.append(response)

            else:
                response = "All we need to do is {}".format(children_names.pop())
                responses.append(response)


        elif transcript in '\t'.join(self.horizontal_queries):
            next_human_action = self.htm.find_next_human_action(self.htm.root,
                                                                self.curr_action.idx)
            response          = "You should {}".format(next_human_action.name)
            responses.append(response)

        elif transcript in '\t'.join(self.bottom_up_queries):

            rospy.loginfo("IN BOTTOM UP")
            if "why are we building a" in transcript:
                node             = self.htm.find_node_by_name(self.htm.root, param)
                self.curr_parent = self.htm.find_parent_node(self.htm.root, node.idx)
                response         = "We are building a {} in order to {}".format(param,
                                                                                self.curr_parent.name)
            elif transcript in "why":
                if not self.curr_parent:
                    rospy.logwarn("Sorry, I didn't understand: \"{}\"".format(transcript))
                else:
                    self.curr_parent = self.htm.find_parent_node(self.htm.root,
                                                                 self.curr_parent.idx)
                    response = "So that we can {}".format(self.curr_parent.name)
            else:
                self.curr_parent = self.htm.find_parent_node(self.htm.root,
                                                                 self.curr_action.idx)
                response = "So that we can {}".format(self.curr_parent.name)

            responses.append(response)


        elif transcript in self.stationary_queries:
            response ="I am {}".format(self.curr_action.name)
            responses.append(response)


        else:
            rospy.logwarn("Sorry, I didn't understand: \"{}\"".format(transcript))

        return responses

    def _baxter_begin(self,utter):
        """
        Checks if the start command has been issued
        """
        if utter:
            regex = r"^(\w+\b\s){0,2}(let's begin|let's start|begin|let us start|begin|let's go)"
            self.START_CMD = re.search(regex, utter.lower())
        else:
            self.START_CMD = False  # than utter is probably None

        return
