cc_library(
    name = "volumetric_display",
    srcs = ["VolumetricDisplay.cpp"],
    hdrs = ["VolumetricDisplay.h"],
    copts = [
        # gluPerspective is deprecated in macOS 10.9
        "-Wno-deprecated-declarations",
    ],
    deps = [
        "@boost",
        "@glew",
        "@glfw",
        "@glm",
    ],
)

cc_binary(
    name = "main",
    srcs = [":main.cpp"],
    linkopts = select({
        "@platforms//os:linux": [
            "-lGL",
            "-lGLU",
        ],
        "@platforms//os:osx": [
            "-framework",
            "OpenGL",
        ],
    }),
    deps = [
        ":volumetric_display",
        "@abseil-cpp//absl/flags:flag",
        "@abseil-cpp//absl/flags:parse",
        "@glm",
    ],
)
