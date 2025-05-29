load("@rules_python//python:defs.bzl", "py_binary")
load("@py_deps//:requirements.bzl", "requirement")

py_binary(
    name = "mapper",
    srcs = ["mapper.py"],
    deps = [
        requirement("python-rtmidi"),
        requirement("python-osc"),
    ],
)
