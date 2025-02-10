#!/usr/bin/env python3

from typing import Final
import logging

from colorama import Fore, Style


# TODO: add current PPU frame/row/column to logs

FORMAT = '%(levelname)s %(filename)s:%(lineno)d %(message)s'

LEVEL_FORMATS: Final = {
	logging.DEBUG: Style.DIM + FORMAT + Style.RESET_ALL,
	logging.INFO: FORMAT + Style.RESET_ALL,
	logging.WARNING: Fore.YELLOW + FORMAT + Style.RESET_ALL,
	logging.ERROR: Fore.RED + FORMAT + Style.RESET_ALL,
	logging.CRITICAL: Style.BRIGHT + Fore.RED + FORMAT + Style.RESET_ALL,
}

FORMATTERS: Final = {
	level: logging.Formatter(fmt) for level, fmt in LEVEL_FORMATS.items()
}


class CustomFormatter(logging.Formatter):
	def format(self, record):
		return FORMATTERS.get(record.levelno).format(record)


def init_logging(
		*,
		stream_level=logging.INFO,
		file_level=None,
		):

	stream_handler = logging.StreamHandler()
	stream_handler.setLevel(stream_level)
	stream_handler.setFormatter(CustomFormatter())
	handlers = [stream_handler]

	if file_level is not None:
		file_handler = logging.FileHandler()
		file_handler.setLevel(file_level)

	root_level = stream_level
	if file_level is not None:
		root_level = min(root_level, file_level)

	logging.basicConfig(
		level=root_level,
		format=FORMAT,
		handlers=handlers,
	)
