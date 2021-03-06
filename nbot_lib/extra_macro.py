from ctypes import *
from traceback import format_exc

from .hook import Hook
from .memory import write_string, read_ulonglong, read_int, BASE_ADDR, read_string
from .saint_coinach import item_sheet, item_names, realm, status_sheet
from .text_pattern import find_signature_address, find_signature_point

quest_sheet = realm.game_data.get_sheet("Quest")
map_sheet = realm.game_data.get_sheet("Map")
event_item_sheet = realm.game_data.get_sheet('EventItem')
event_item_names = {row.key: row['Singular'] for row in event_item_sheet}

item_name_to_id = {row['Name']: row.key for row in item_sheet}
quest_name_to_id = {row['Name']: row.key for row in quest_sheet}
quest_names = {row.key: row['Name'] for row in quest_sheet}
maps = {}
for row in map_sheet: maps.setdefault(getattr(row['TerritoryType'], 'key', 0), {})[row['MapIndex']] = row.key
status_name_to_id = {}
for row in status_sheet: status_name_to_id.setdefault(row['Name'], []).append(row.key)


def raw_to_in_game_coord(pos): return pos / 1000


def in_game_to_raw_coord(pos): return pos * 1000


c1 = 41 / 2048


def in_game_to_map_coord(pos, scale=100, offset=0): return (pos + offset) * c1 + 2050 / scale + 1


def map_to_in_game_coord(pos, scale=100, offset=0): return (pos - 1 - 2050 / scale) / c1 - offset


def parse_item(name=None, item_id=None, hq=None, collect=None, no_tag=None, ):
    if item_id is None and name is None: return
    if item_id is None:
        item_id = item_name_to_id.get(name)
        if item_id is None: return
    else:
        item_id = int(item_id)
    if name is None:
        name = item_names.get(item_id) or event_item_names.get(item_id) or f'unk_item:{item_id}'
    if hq:
        item_id += 1000000
        if not no_tag: name += '\ue03c'
    if collect:
        item_id += 500000
        if not no_tag: name += '\ue03d'
    return f"<fixed(200,4,{item_id},1,0,0,{name})>"


def parse_quest(name=None, quest_id=None, ):
    if name is None and quest_id is None: return
    if quest_id is None:
        quest_id = quest_name_to_id.get(name)
        if quest_id is None: return
    else:
        quest_id = int(quest_id)
        if quest_id < 65536:
            quest_id += 65536
    if name is None:
        name = quest_names.get(quest_id) or f'unk_quest:{quest_id}'
    return f"<fixed(200,12,{quest_id - 65536},0,0,0,{name})>"


def parse_pos(map_id=None, territory_id=None, x=None, y=None, z=None, map_x=None, map_y=None, ):
    if map_id is None and territory_id is None:
        return
    if map_id: map_id = int(map_id)
    if territory_id: territory_id = int(territory_id)
    if map_id is None:
        maps.get(territory_id, {}).get(0, 0)
    map_row = map_sheet[map_id]
    if territory_id is None:
        territory_id = getattr(map_row['TerritoryType'], 'key', 0)
    if x is None:
        if map_x:
            x = map_to_in_game_coord(float(map_x), map_row["SizeFactor"], map_row["Offset{X}"])
        else:
            return
    else:
        x = float(x)
    if y is None:
        if map_y:
            y = map_to_in_game_coord(float(map_y), map_row["SizeFactor"], map_row["Offset{Y}"])
        else:
            return
    else:
        y = float(y)
    if z is None: z = 0
    else: z = float(z)
    return f"<fixed(200,3,{territory_id},{map_id},{x * 1000:.0f},{y * 1000:.0f},{z:.0f})>"


def parse_status(status_id=None, name=None, ):
    if status_id is None and name is None: return
    if status_id is None:
        status_id = min(status_name_to_id.get(name, [0]))
    return f"<fixed(200,10,{status_id},0,0)>"


def parse_macro(marco: list[str]):
    args = {
        m[0]: m[1] if len(m) > 1 else True
        for m in (m.split('=', 1) for m in marco[1:])
    }
    match marco[0]:
        case 'item' | 'i':
            return parse_item(**args)
        case 'quest' | 'q':
            return parse_quest(**args)
        case 'ppos' | 'p':
            return parse_pos(**args)
        case 'status' | 's':
            return parse_status(**args)


class ExtraMacro:

    def __init__(self):

        self.c1 = CFUNCTYPE(c_int64, c_int64, c_int64, c_int64)(find_signature_address(
            "48 89 5C 24 ? 48 89 6C 24 ? 48 89 74 24 ? 57 48 83 EC ? 48 8B D9 49 8B F8 48 81 C1 ? ? ? ?",
        ) + BASE_ADDR)
        self.c2 = CFUNCTYPE(c_int64, c_int64, c_int64)(find_signature_address(
            "48 89 5C 24 ? 48 89 74 24 ? 57 48 83 EC ? 48 8B 79 ? 48 8B F2 48 8B 52 ?"
        ) + BASE_ADDR)
        self.c3 = CFUNCTYPE(c_int64, c_int64)(find_signature_address(
            "80 79 ? ? 75 ? 48 8B 51 ? 41 B8 ? ? ? ?"
        ) + BASE_ADDR)
        self.off = read_int(read_ulonglong(find_signature_point(
            "48 8D 05 * * * * 4C 89 61 ? 4C 8B FA"
        ) + BASE_ADDR + 0x30) + 3)
        self.hook = self.MacroParseHook(find_signature_address(
            "40 55 53 56 48 8B EC 48 83 EC ? 48 8B 05 ? ? ? ? 48 33 C4 48 89 45 ? 48 8B F1",
        ) + BASE_ADDR, self.c1, self.c2, self.c3, self.off)
        self.hook.install_and_enable()

    def unload(self):
        self.hook.uninstall()

    class MacroParseHook(Hook):
        restype = c_int64
        argtypes = [c_int64, POINTER(c_int64)]

        def __init__(self, func_address: int, c1, c2, c3, off):
            super().__init__(func_address)
            self.c1 = c1
            self.c2 = c2
            self.c3 = c3
            self.off = off

        def hook_function(self, a1, a2):
            try:
                cmd = read_string(a2[0], encode=None)
                try:
                    end = cmd.find(b'>')
                except ValueError:
                    return self.original(a1, a2)
                if cmd[1] == 47:
                    write_string(a2[0], cmd[:end].replace(b'</', b'<', 1) + cmd[end:])
                    a2[0] += end
                    return 0
                ans = parse_macro(cmd[1:end].decode('utf8', 'ignore').split(' '))
                if ans:
                    write_string(read_ulonglong(a1 + 136), ans)
                    a2[0] += end + 1
                    buffer = (c_char * 1024)()
                    v = self.c1(read_ulonglong(a1 + 912) + self.off, addressof(buffer), read_ulonglong(a1 + 136))
                    self.c2(a1 + 32, v)
                    self.c3(addressof(buffer))
                    return 0xffffffff
            except Exception as e:
                windll.user32.MessageBoxW(0, "error occur:\n" + format_exc(), "parse macro error", 0x10)
            return self.original(a1, a2)
