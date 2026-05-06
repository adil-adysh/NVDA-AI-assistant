"""This tool allows generation of gettext .mo compiled files, pot files from source code files
and pot files for merging.

Three new builders are added into the constructed environment:

- gettextMoFile: generates .mo file from .pot file using msgfmt.
- gettextPotFile: Generates .pot file from source code files.
- gettextMergePotFile: Creates a .pot file appropriate for merging into existing .po files.

To properly configure get text, define the following variables:

- gettext_package_bugs_address
- gettext_package_name
- gettext_package_version


"""

from functools import partial
import tempfile
import subprocess
from pathlib import Path

from SCons.Action import Action


def exists(env):
	return True


XGETTEXT_COMMON_ARGS = (
	"--msgid-bugs-address='$gettext_package_bugs_address' "
	"--package-name='$gettext_package_name' "
	"--package-version='$gettext_package_version' "
	"--keyword=translate "
	"--keyword=pgettext:1c,2 "
	"-c -o $TARGET $SOURCES"
)


def _run_command(command: list[str], target, source, env):
	completed = subprocess.run(command, check=False)
	if completed.returncode:
		raise subprocess.CalledProcessError(completed.returncode, command)
	return completed.returncode


def _xgettext_command(target, source, env, *, omit_header: bool):
	file_list_path = None
	try:
		with tempfile.NamedTemporaryFile("w", encoding="utf-8", newline="\n", delete=False) as file_list:
			for node in source:
				file_list.write(str(node))
				file_list.write("\n")
			file_list_path = file_list.name
		command = [
			"xgettext",
			f"--msgid-bugs-address={env.subst('$gettext_package_bugs_address')}",
			f"--package-name={env.subst('$gettext_package_name')}",
			f"--package-version={env.subst('$gettext_package_version')}",
			"--keyword=translate",
			"--keyword=pgettext:1c,2",
			"-c",
			f"--files-from={file_list_path}",
		]
		if omit_header:
			command.extend(["--omit-header", "--no-location"])
		command.extend(["-o", str(target[0])])
		return _run_command(command, target, source, env)
	finally:
		if file_list_path:
			Path(file_list_path).unlink(missing_ok=True)


def _msgfmt_command(target, source, env):
	command = ["msgfmt", "-o", str(target[0]), str(source[0])]
	return _run_command(command, target, source, env)


def generate(env):
	env.SetDefault(gettext_package_bugs_address="example@example.com")
	env.SetDefault(gettext_package_name="")
	env.SetDefault(gettext_package_version="")

	env["BUILDERS"]["gettextMoFile"] = env.Builder(
		action=Action(_msgfmt_command, "Compiling translation $SOURCE"),
		suffix=".mo",
		src_suffix=".po",
	)

	env["BUILDERS"]["gettextPotFile"] = env.Builder(
		action=Action(partial(_xgettext_command, omit_header=False), "Generating pot file $TARGET"),
		suffix=".pot",
	)

	env["BUILDERS"]["gettextMergePotFile"] = env.Builder(
		action=Action(partial(_xgettext_command, omit_header=True), "Generating pot file $TARGET"),
		suffix=".pot",
	)
