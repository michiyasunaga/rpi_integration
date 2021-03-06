# Apprentice Agents Learner [![Build Status](https://travis-ci.org/ScazLab/rpi_integration.svg?branch=master)](https://travis-ci.org/ScazLab/rpi_integration)

## Description

This repository is used to interface with the docker images developed for our integration work with RPI. Docker images are `leia/ontosem` and `leia/agents`, and they expose a REST API once opened.

Once opened, the REST API is available on `0.0.0.0:5002`

 * `/learn` -> `POST` raw JSON in the format for the learner; you can post one or more sequential inputs (utterances and actions); the response will be the HTN in JSON format (the current complete HTN, with the latest inputs included)
 * `/alpha/gettree` -> `GET`; returns the current HTN (without modifying it):
   * use `?format=json` to get the same response format as `/learn`
   * use `?format=pretty` to get a human readable version
 * `/alpha/reset` -> `DELETE`; this will clear the current tree (in lieu of killing and restarting the docker containers)
 * `/alpha/maketree` -> deprecated, ignore this command for now

## Dependencies

* `task-models`, available [here](https://github.com/ScazLab/task-models), is used to perform integration tests.

## Installation

Pull the required images from the docker repo:

```
docker login --username=[username]
docker pull leia/ontosem:1.0.0
docker pull leia/agents:latest.yale
```

## Usage

Run the compose file to turn on 3 containers and their respective services `docker-compose -p rpi_integration -f ./docker-compose.yml up`

After the docker containers are opened, you can query things via `curl` in a terminal window.

Examples of `curl` requests:

 * `curl -i -X GET http://0.0.0.0:5002/alpha/gettree?format=pretty` to get the status of the tree in ascii format
 * `curl -i -X GET http://0.0.0.0:5002/alpha/gettree?format=json` to get the status of the tree in json format
 * `curl -s -H "Content-type: application/json" -X POST -d '[["u", "We will build a chair."], ["a", "get-screwdriver"]]' http://0.0.0.0:5002/learn` to ask the system to learn a new htm from sequence of actions and utterances
 * `curl -i -X DELETE http://0.0.0.0:5002/alpha/reset` to clear the learning

Example of sequences of actions and utterances:

 * `[["u","I will build a chair."], ["u", "I'm building a leg."], ["a", "get-bracket-foot"], ["a", "get-dowel"]]`
 * `[["u", "We will build a chair."], ["a", "get-screwdriver"]`

## Testing

- `docker-compose -p rpi_integration -f ./docker-compose.yml up`: runs the container and exposes server ports
- `python -m unittest discover tests`: runs all the tests

In order to test the HTM controller run:

- `rostest rpi_integration test_htm_controller.test --text`

## Available actions

If you are posting an action (“a”), then the valid list includes the following keys (you can, alternatively, post any of the below as a “u” using the value):

 * `get-screwdriver`: "Get a screwdriver.",
 * `get-bracket-foot`: "Get a foot bracket.",
 * `get-bracket-front`: "Get a front bracket.",
 * `get-bracket-back-right`: "Get the back bracket on the right side.",
 * `get-bracket-back-left`: "Get the back bracket on the left side.",
  * `get-top-bracket`: "Get the top bracket.",
 * `get-dowel`: "Get a dowel.",
 * `hold-dowel`: "Hold the dowel.",
 * `release-dowel`: "Release the dowel.",
 * `get-seat`: "Get the seat.",
 * `hold-seat`: "Hold the seat.",
 * `get-back`: "Get the back.",
 * `hold-back`: "Hold the back."

