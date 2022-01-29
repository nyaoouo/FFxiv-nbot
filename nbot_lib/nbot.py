import time
import os
from ctypes import *
from pathlib import Path
from queue import Queue, Empty
from threading import Thread
from importlib import reload
from inspect import signature
from traceback import format_exc


def do_output(message: str | bytes, command: str | bytes = b'/e'):
    pass


def run():
    from .memory import PROCESS_FILENAME, BASE_ADDR, read_memory
    game_base_dir = Path(PROCESS_FILENAME).parent.parent
    if (game_base_dir / "FFXIVBoot.exe").exists() or (game_base_dir / "rail_files" / "rail_game_identify.json").exists():
        os.environ['game_language'] = "chs"
        os.environ['game_ext'] = '3'
    else:
        os.environ['game_language'] = "en"
        os.environ['game_ext'] = '4'

    from .text_pattern import find_signature_address, find_signature_point
    print_chat_log_offset = find_signature_address("40 55 53 56 41 54 41 57 48 8D AC 24 ?? ?? ?? ?? 48 81 EC 20 02 00 00 48 8B 05")
    do_text_command_offset = find_signature_address("48 89 5C 24 ? 57 48 83 EC 20 48 8B FA 48 8B D9 45 84 C9")
    text_command_ui_module_offset = find_signature_point("48 8B 05 * * * * 48 8B D9 8B 40 14 85 C0")
    frame_inject_offset = find_signature_address("4C 8B DC 53 56 48 81 EC ? ? ? ? 48 8B 05 ? ? ? ? 48 33 C4 48 89 84 24 ? ? ? ? 48 83 B9")

    from .memory.struct_factory import OffsetStruct
    ui_module = read_memory(POINTER(c_int64), text_command_ui_module_offset + BASE_ADDR)
    __do_text_command = CFUNCTYPE(c_int64, c_void_p, c_void_p, c_int64, c_char)(do_text_command_offset + BASE_ADDR)
    TextCommandStruct = OffsetStruct({"cmd": c_void_p, "t1": c_longlong, "tLength": c_longlong, "t3": c_longlong}, full_size=400)

    def _do_text_command(command: str | bytes):
        if isinstance(command, str): command = command.encode('utf-8')
        cmd_size = len(command)
        cmd = OffsetStruct({"cmd": c_char * cmd_size}, full_size=cmd_size + 30)(cmd=command)
        arg = TextCommandStruct(cmd=addressof(cmd), t1=64, tLength=cmd_size + 1, t3=0)
        return __do_text_command(ui_module[0], addressof(arg), 0, 0)

    global do_output

    def do_output(message: str | bytes, command: str | bytes = b'/e'):
        if isinstance(message, str): message = message.encode('utf-8')
        if isinstance(command, str): command = command.encode('utf-8')
        for line in message.strip().split(b'\n'):
            frame_works.put((_do_text_command, (command + b' ' + line,), {}))

    from .hook import Hook
    from .se_string import ChatLog, get_message_chain

    class PrintChatLogHook(Hook):
        restype = c_int64
        argtypes = [c_int64, c_ushort, POINTER(c_char_p), POINTER(c_char_p), c_uint, c_ubyte]

        def __init__(self, func_address: int):
            super().__init__(func_address)

        def hook_function(self, manager, channel_id, p_sender, p_msg, sender_id, parm):
            try:
                on_log(ChatLog(
                    time.time(),
                    channel_id,
                    get_message_chain(bytearray(p_sender[0])),
                    get_message_chain(bytearray(p_msg[0]))
                ))
            except:
                windll.user32.MessageBoxW(0, "error occur:\n" + format_exc(), "on log error", 0x10)
            finally:
                return self.original(manager, channel_id, p_sender, p_msg, sender_id, parm)

    def on_log(chat_log: ChatLog):
        args = chat_log.messages_text.split(' ')
        if chat_log.channel_id == 56:
            match args[0]:
                case '$close':
                    nonlocal work
                    work = False
                    return
                case '$reload':
                    load_process()
                    return

        p = __import__('nbot_process')
        if process_arg_cnt and chat_log.channel_id == p.listen_channel_id:
            Thread(target=p.process, args=(args, chat_log, do_output)[:process_arg_cnt]).start()

    frame_works = Queue()

    class FrameInjectHook(Hook):
        argtypes = [c_void_p, c_void_p]

        def hook_function(self, *oargs):
            try:
                while True:
                    call, args, kwargs = frame_works.get(block=False)
                    call(*args, **kwargs)
            except Empty:
                pass
            return self.original(*oargs)

    process_arg_cnt = 0

    def load_process():
        nonlocal process_arg_cnt
        process_arg_cnt = len(signature(reload(__import__('nbot_process')).process).parameters)

    load_process()
    work = True
    chat_hook = PrintChatLogHook(print_chat_log_offset + BASE_ADDR)
    chat_hook.install_and_enable()
    frame_hook = FrameInjectHook(frame_inject_offset + BASE_ADDR)
    frame_hook.install_and_enable()

    from .extra_macro import ExtraMacro
    extra_marco = ExtraMacro()

    do_output("n bot start")
    while work: time.sleep(1)

    extra_marco.unload()
    chat_hook.uninstall()
    frame_hook.uninstall()
