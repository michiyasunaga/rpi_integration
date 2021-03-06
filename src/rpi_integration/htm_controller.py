#!/usr/bin/env python
# import sys
# sys.path.append("/home/michi/src/ros_devel_ws/src/rpi_integration/src")

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

def transcript_in_query_list(transcript, query_list):
    """
    Checks if query is in one of the list and whether its parameterized
    Will return a boolean, or string if parameterized.
    """
    param_indicator = "{}"

    for q in query_list:
        if param_indicator in q:
            q_list      = q.split()
            trans_list  = transcript.split()

            param_index = q_list.index(param_indicator)

            try:
                q_list.pop(param_index)
                param = trans_list.pop(param_index)
            except IndexError: # Then the two lists dont match
               continue

            if trans_list == q_list:
                return param

        elif transcript in q:
            return True

    return False


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

    natural_Names = {
        "GET(seat)":                "Get the seat.",
        "GET(back)":                "Get the back.",
        "GET(dowel)":               "Get a dowel.",
        "GET(dowel-top)":           "Get the top dowel.",
        "GET(FOOT_BRACKET)":        "Get a foot bracket.",
        "GET(bracket-front)":       "Get a front bracket.",
        "GET(bracket-top)":        "Get the top bracket.",
        "GET(bracket-back-right)":  "Get the back right bracket.",
        "GET(bracket-back-left)":   "Get the back left bracket.",
        "GET(screwdriver)":         "Get a screwdriver.",
        "HOLD(dowel)":              "Hold the dowel.",
        "HOLD(seat)":               "Hold the seat.",
        "HOLD(back)":               "Hold the back.",
        "FASTEN(brackets)":         "Fasten the brackets.",
        "FASTEN(legs)":             "Fasten the legs.",
        "FASTEN(back)":             "Fasten the back.",
        "INSERT(dowel)":            "Insert a dowel.",
        # "Start":                    "Let's start.",
        "BUILD CHAIR":              "Build a chair.",
        "Parallelized Subtasks of BUILD CHAIR": "Parallelize subtasks of building a chair.",
        "REQUEST-ACTION GIVE SCREWDRIVER": "Retrieve a screwdriver",
        "BUILD SEAT":               "Build the seat.",
        "BUILD ARTIFACT-LEG":       "Build a leg.",
        "FASTEN ARTIFACT-LEGs TO SEAT": "Fasten the legs to the seat.",
        "BUILD BACK-OF-OBJECT": "Build the seat back.",
        "BUILD TOP-OF-OBJECT": "Build the top part of the chiar.",
        "Parallelized Subtasks of BUILD TOP-OF-OBJECT": "Parallelize subtasks of building the top of the chiar.",
        "FASTEN VERTICAL ARTIFACTs": "Fastern dowels",
        "FASTEN VERTICAL ARTIFACT": "Fastern a dowel",
        "FASTEN BACK-OF-OBJECT TO ARTIFACT": "Fasten the seat back to the chair",
        "FASTEN TOP ARTIFACTs TO BACK-OF-OBJECT": "Fasten the top part to the seat back"
    }

    def to_natural_Name(self, name):
        if name in self.natural_Names:
            return self.natural_Names[name].lower()
        else:
            return name

    def __init__(self):
        self.param_prefix       = "/rpi_integration"
        self.json_path          = rospy.get_param(self.param_prefix + '/json_file')

        self.autostart          = rospy.get_param(self.param_prefix + '/autostart')
        self.use_stt            = rospy.get_param(self.param_prefix + '/use_stt', False)
        self.use_tts            = rospy.get_param(self.param_prefix + '/use_tts', False)

        self.begin_task_queries   = rospy.get_param(self.param_prefix + '/begin_task')
        self.top_down_queries   = rospy.get_param(self.param_prefix + '/top_down')
        self.bottom_up_queries  = rospy.get_param(self.param_prefix + '/bottom_up')
        self.horizontal_queries = rospy.get_param(self.param_prefix + '/horizontal')
        self.stationary_queries = rospy.get_param(self.param_prefix + '/stationary')

        self.htm                = json_to_htm(self.json_path)
        self.last_r             = finished_request

        self.do_query           = rospy.get_param(self.param_prefix + "/do_query", False)
        self._learner_pub       = rospy.Publisher('web_interface/json',
                                                  String, queue_size =10)
        self._listen_sub        = rospy.Subscriber(self.STT_TOPIC, #self.SPEECH_SERVICE,
                                                   transcript, self._listen_query_cb)

        self.curr_parent        = None
        self.lock               = Lock()

        BaseController.__init__(
            self,
            use_left=True, #left=True,
            use_right=True, #right=True,
            use_stt=self.use_stt, #speech=self.use_stt,
            use_tts=False, #listen=False,
            recovery=True,
        )
        RESTUtils.__init__(self)

	self.testing = True
        if self.testing:
            self.START_CMD      = True
        else:
            self.START_CMD      = False

        self.START_TASK_CMD      = False
        self.LISTENING          = False

        # self.delete()
        # self._train_learner_from_file()
        rospy.loginfo('Ready!')

    @property
    def robot_actions(self):
        return self._get_actions(self.task_node.root)

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
            # self._baxter_begin(msg.transcript.lower().strip())
            self._baxter_begin_task(msg.transcript.lower().strip())
            self.LISTENING = False

        # if not self.START_CMD:
        #     response = self._baxter_begin_task(msg.transcript.lower().strip())
        #     if self.use_stt:
        #         utterance        = SpeechRequest()
        #         utterance.mode   = utterance.SAY
        #         utterance.string = response
        #
        #         self.speech(utterance)
        #     else:
        #         rospy.loginfo(utterance)

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
        """
        Parses utterance to determine type of query
        Returns a list of responses for robot to say.
        """
        responses        = []

        # These check if the transcript are in one of the lists defined in param server.
        # these params code be strings, which indicates a match with a parameterized query.
        param_top_down   = transcript_in_query_list(transcript, self.top_down_queries)
        param_bottom_up  = transcript_in_query_list(transcript, self.bottom_up_queries)
        param_horizontal = transcript_in_query_list(transcript, self.horizontal_queries)
        param_stationary = transcript_in_query_list(transcript, self.stationary_queries)

        if param_top_down:
            if isinstance(param_top_down, str): # if true, then is paramaterized query
                # Finds node associated with parameter
                task = self.htm.find_node_by_name(self.htm.root, param_top_down)

                if not task: # Couldn't find the node by name
                    rospy.logerr("Couldnt find node by name {}".format(param_top_down))
                    return None
                else:
                    children_names = [c.name for c in task.children]
                    response       = "In order to {}".format(self.to_natural_Name(task.name))
            else: # Not parameterized so go down HTM from top.
                task           = self.htm.root.children[0]
                children_names = [c.name for c in task.children]
                response       = "Our task is to {}".format(self.to_natural_Name(task.name))

            responses.append(response)

            if len(children_names) > 1:
                #response = "We need to do {} things".format(len(children_names))
                #responses.append(response)

                response = "First, we will {}".format(self.to_natural_Name(children_names.pop()))
                responses.append(response)

                while(len(children_names) > 1):
                    response = "Then, we will {}".format(self.to_natural_Name(children_names.pop()))
                    responses.append(response)

                response = "Finally, we will {}".format(self.to_natural_Name(children_names.pop()))
                responses.append(response)

            else:
                response = "All we need to do is {}".format(self.to_natural_Name(children_names.pop()))
                responses.append(response)


        elif param_horizontal:
            next_human_action = self.htm.find_next_human_action(self.htm.root,
                                                                self.curr_action.idx)
            response          = "You should {}".format(self.to_natural_Name(next_human_action.name))
            # set this so that you can ask follow up query (e.g. "why?"")
            self.curr_parent  = self.htm.find_parent_node(self.htm.root,
                                                         self.next_human_action.idx)
            responses.append(response)

        elif param_bottom_up:

            rospy.loginfo("IN BOTTOM UP")
            rospy.loginfo(transcript)

            if isinstance(param_bottom_up, str):
                node             = self.htm.find_node_by_name(self.htm.root, param_bottom_up)
                self.curr_parent = self.htm.find_parent_node(self.htm.root, node.idx)
                response         = "We are building a {} in order to {}".format(self.to_natural_Name(param_bottom_up),
                                                                                self.to_natural_Name(self.curr_parent.name))
            elif transcript in "why": #  Response to "why" is conditional on previous query
                if not self.curr_parent:
                    rospy.logwarn("Sorry, I didn't understand: \"{}\"".format(transcript))
                else:
                    self.curr_parent = self.htm.find_parent_node(self.htm.root,
                                                                 self.curr_parent.idx)
                    response = "So that we can {}".format(self.to_natural_Name(self.curr_parent.name))
            else:
                self.curr_parent = self.htm.find_parent_node(self.htm.root,
                                                             self.curr_action.idx)
                response = "So that we can {}".format(self.to_natural_Name(self.curr_parent.name))

            responses.append(response)


        elif param_stationary:
            response = "Currently, I am {}".format(self.to_natural_Name(self.curr_action.name))
            # set this so that you can ask follow up query (e.g. "why?"")
            self.curr_parent = self.htm.find_parent_node(self.htm.root,
                                                         self.curr_action.idx)
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

    def _baxter_begin_task(self, transcript):
        param_begin_task   = transcript_in_query_list(transcript, self.begin_task_queries)
        # response        = None

        if param_begin_task:
            self.node_task = "build a {}".format(param_begin_task)
            self.START_CMD = True
            # response = "okay, let's build a {}".format(param_begin_task)
        else:
            rospy.logwarn("Sorry, I didn't understand: \"{}\"".format(transcript))
            self.START_CMD = False
        # return response
