from __future__ import annotations

import concurrent.futures as cf
import sys

from comps.termhelper_banner_common import BannerError, RemoteBannerManager, build_common_parser, parse_hosts


def restore_on_host(host: str, args) -> None:
    with RemoteBannerManager(
        host,
        username=args.username,
        password=args.password,
        sudo_password=args.sudo_password,
        port=args.port,
        timeout=args.timeout,
    ) as manager:
        manager.restore_banner()


def main() -> int:
    parser = build_common_parser("Otkatyvaet custom termhelper-banner na spiske serverov.")
    args = parser.parse_args()

    try:
        hosts = parse_hosts(args.hosts, args.hosts_file)
    except BannerError as exc:
        print(exc, file=sys.stderr)
        return 2

    failures: list[tuple[str, str]] = []
    max_workers = max(1, min(args.workers, len(hosts)))

    print(
        f"Zapuskayu otkat na {len(hosts)} host(ah), parallelno do {max_workers}, timeout {args.timeout}s.",
        flush=True,
    )

    with cf.ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_to_host = {executor.submit(restore_on_host, host, args): host for host in hosts}

        for future in cf.as_completed(future_to_host):
            host = future_to_host[future]
            try:
                future.result()
            except Exception as exc:  # noqa: BLE001
                failures.append((host, str(exc)))
                print(f"[{host}] oshibka: {exc}", flush=True)
            else:
                print(f"[{host}] otkat vypolnen", flush=True)

    if failures:
        print("\nNe udalos obrabotat hosty:", file=sys.stderr)
        for host, error in failures:
            print(f" - {host}: {error}", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
