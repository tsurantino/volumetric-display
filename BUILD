cc_library(
    name = "volumetric_display",
    srcs = ["VolumetricDisplay.cpp"],
    hdrs = ["VolumetricDisplay.h"],
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
    linkopts = [
      "-framework", "OpenGL",
    ],
    deps = [
        ":volumetric_display",
        "@glm",
        "@abseil-cpp//absl/flags:flag",
        "@abseil-cpp//absl/flags:parse",
    ],
)
