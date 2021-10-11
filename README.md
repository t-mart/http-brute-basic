# http-basic-brute

An HTTP basic authentication brute forcer.

![Demo](https://raw.githubusercontent.com/t-mart/http-brute-basic/master/docs/demo.gif)

## Features

- asyncio makes it pretty fast
- progress bar shows the request rate

## Running

First, install the dependencies

```shell
$ pip install -r requirements.txt
```

Then, use the help command to see available options.

```shell
$ python -m brute --help
```

### Running a testing server

There's a little test server too to test against.

```shell
$ python -m server --help
```

## TODO

- if an exception is raised in the tasks, we don't know about it because we're only awaiting
  the event.
- fix jumpy tdqm progress bar? <https://github.com/tqdm/tqdm/pull/1262>
