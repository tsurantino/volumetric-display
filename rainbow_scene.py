from artnet import HSV, RGB, Scene


class RainbowScene(Scene):
    def __init__(self, config):
        pass

    def render(self, raster, time):
        """Renders a pattern on a single, large raster."""
        for y in range(raster.height):
            for x in range(raster.width):
                for z in range(raster.length):
                    idx = y * raster.width + x + z * raster.width * raster.height

                    # Hue is now based on the simple coordinates of the large raster
                    hue = (x + y + z) * 4 + time * 50

                    raster.data[idx] = RGB.from_hsv(HSV(int(hue) % 256, 255, 255))
