#!/usr/bin/env python3
"""Generate synthetic HOTAS reports independently of either bridge."""

from trace import ROOT, trace, write_trace


def packet(*, twist=4300, rocker=4021, x=512, y=512, z=128, hat=8,
           buttons=0, report_id=1):
    """Encode the original 64-byte wire report from SPEC section 2."""
    data = bytearray(64)
    data[0] = report_id
    data[1:3] = x.to_bytes(2, "little")
    data[3:5] = y.to_bytes(2, "little")
    data[5:11] = bytes((z, 127, 255, 255, 128, 128))
    data[11:14] = (hat | (buttons << 4) | (0x1F << 19)).to_bytes(3, "little")
    data[18:20] = twist.to_bytes(2, "little")
    data[24:26] = rocker.to_bytes(2, "little")
    return bytes(data)


def sweeps():
    # Cross both default bounds, then sweep back using the widened limits.
    for word, low, high in (("twist", 900, 7800), ("rocker", 1090, 7100)):
        for direction in (range(low, high + 1), range(high, low - 1, -1)):
            yield from (packet(**{word: raw}) for raw in direction)
    for raw in range(300):
        yield packet(twist=raw, rocker=raw)
    yield packet(twist=300, rocker=300)
    yield packet(twist=65535, rocker=65535)
    yield packet(twist=1000, rocker=1191)


def controls():
    yield packet(x=0, y=0, z=0)
    for x, y, z in ((1023, 0, 255), (0, 1023, 0), (1023, 1023, 255)):
        yield packet(x=x, y=y, z=z)
    for hat in range(16):
        yield packet(hat=hat)
    for button in range(15):
        yield packet(buttons=1 << button)
        yield packet()
    yield packet(buttons=0x7FFF)
    yield packet()
    yield packet()
    yield packet(twist=65000, rocker=65000, report_id=2)
    yield packet(twist=65000, rocker=65000)[:63]
    yield packet() + b"\xff"
    yield packet(twist=1000, rocker=1191, hat=7)


def boundaries():
    # Include the default twist deadzone edges (4300 +/- 429/442).
    for raw in (3869, 3870, 3871, 3872, 3873, 4740, 4741, 4742, 4743, 4744):
        yield packet(twist=raw)
    # The inverted rocker edges are at raw 4021 + 356.4 and 4021 - 339.6.
    for raw in (3679, 3680, 3681, 3682, 3683, 4375, 4376, 4377, 4378, 4379):
        yield packet(rocker=raw)


def ties():
    # Both adjusted spans are 2048 and the deadzone is zero. On the lower
    # half these include 0.5 and 1.5; at the upper midpoint the value is 255.5.
    for distance in (1, 2, 3, 5, 6, 7, 9, 10, 11, 1023, 1024, 1025):
        yield packet(twist=4300 - distance, rocker=4021 + distance)
        yield packet(twist=4300 + distance, rocker=4021 - distance)


def main():
    for name, packets in (
        ("sweeps", sweeps()),
        ("controls", controls()),
        ("boundaries", boundaries()),
        ("ties", ties()),
    ):
        write_trace(ROOT / "traces" / f"{name}.json", trace(enumerate(packets, 1)))


if __name__ == "__main__":
    main()
