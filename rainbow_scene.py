from artnet import HSV, RGB, Scene


class RainbowScene(Scene):
    def __init__(self, **kwargs):
        pass

    def render(self, raster, time):
        """Renders a pattern on a single, large raster."""
        for y in range(raster.height):
            for x in range(raster.width):
                for z in range(raster.length):
                    # Calculate hue based on voxel position and time
                    hue = (x + y + z) * 4 + time * 50

                    # Convert the HSV color to an RGB object
                    color = RGB.from_hsv(HSV(int(hue) % 256, 255, 255))

                    raster.set_pix(x, y, z, color)
