#!/usr/bin/env python3
import argparse


def channel_first(channels, ways, count):
    ch = way = 0
    out = []
    for _ in range(count):
        out.append((ch, way))
        ch += 1
        if ch == channels:
            ch = 0
            way = (way + 1) % ways
    return out


def way_first(channels, ways, count):
    ch = way = 0
    out = []
    for _ in range(count):
        out.append((ch, way))
        way += 1
        if way == ways:
            way = 0
            ch = (ch + 1) % channels
    return out


def page_first(channels, ways, pages_per_block, count):
    ch = way = page = 0
    out = []
    for _ in range(count):
        out.append((ch, way, page))
        page += 1
        if page == pages_per_block:
            page = 0
            ch += 1
            if ch == channels:
                ch = 0
                way = (way + 1) % ways
    return out


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--channels", type=int, default=8)
    parser.add_argument("--ways", type=int, default=8)
    parser.add_argument("--pages-per-block", type=int, default=128)
    parser.add_argument("--count", type=int, default=20)
    args = parser.parse_args()

    cf = channel_first(args.channels, args.ways, args.count)
    wf = way_first(args.channels, args.ways, args.count)
    pf = page_first(args.channels, args.ways, args.pages_per_block, args.count)

    if args.channels > 1 and args.ways > 1:
        assert cf != wf, "channel-first and way-first must differ"
    assert len(set(pf[: min(args.pages_per_block, args.count)])) == min(
        args.pages_per_block, args.count
    ), "page numbers must advance while channel/way remain fixed"
    assert all(item[:2] == (0, 0) for item in pf[: min(args.pages_per_block, args.count)])

    print("channel-first:", cf)
    print("way-first:    ", wf)
    print("page-first:   ", pf)
    print("PASS")


if __name__ == "__main__":
    main()
