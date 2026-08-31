#!/usr/bin/env python3

import argparse
import subprocess

import colorama

parser = argparse.ArgumentParser(description="Code checks")
parser.add_argument("--skip-flake", action="store_true")
parser.add_argument("--debug", action="store_true")
parser.add_argument("--fix", action="store_true", help="Apply fixes instead of check-only")
parser.add_argument(
    "--skip-migrations", action="store_true", help="Skip migration checks"
)
args = parser.parse_args()

DEBUG = args.debug


def cmd(line):
    if DEBUG:
        print(colorama.Style.DIM + "% " + line + colorama.Style.RESET_ALL)
    try:
        output = subprocess.check_output(line, shell=True).decode("utf-8")
        if DEBUG:
            print(colorama.Style.DIM + output + colorama.Style.RESET_ALL)
        return output
    except subprocess.CalledProcessError as e:
        print(colorama.Fore.RED + e.stdout.decode("utf-8") + colorama.Style.RESET_ALL)
        exit(1)


def status(line):
    print(colorama.Fore.GREEN + f">>> {line}..." + colorama.Style.RESET_ALL)


if __name__ == "__main__":
    colorama.init()

    if not args.skip_migrations:
        if args.fix:
            status("Making any missing migrations")
            cmd("python manage.py makemigrations")
        else:
            status("Checking for missing migrations")
            # Use check-only to avoid creating files locally
            cmd("python manage.py makemigrations --check --dry-run")

    if args.fix:
        status("Running black (fix)")
        cmd("black --line-length=119 temba")
    else:
        status("Running black (check)")
        cmd("black --check --diff --line-length=119 temba")

    if not args.skip_flake:
        status("Running flake8")
        cmd("flake8 temba")

    if args.fix:
        status("Running isort (fix)")
        cmd("isort -rc temba")
    else:
        status("Running isort (check)")
        # -c/--check-only returns non-zero if changes would be made; --diff shows what
        cmd("isort -rc -c --diff temba")

    # if any code changes were made, exit with error
    if cmd("git diff temba locale"):
        print("👎 " + colorama.Fore.RED + "Changes to be committed")
        exit(1)
    else:
        print("👍 " + colorama.Fore.GREEN + "Code looks good. Make that PR!")