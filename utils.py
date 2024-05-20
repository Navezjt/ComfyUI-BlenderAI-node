import struct
import queue
import platform
import time
from pathlib import Path
from threading import Thread
from functools import lru_cache
from urllib.parse import urlparse
from .kclogger import logger
from .translations import LANG_TEXT
from .timer import Timer
from .datas import IMG_SUFFIX, get_bl_version
translation = {}


def read_json(path: Path | str) -> dict:
    import json
    encodings = ["utf8", "gbk"]
    for encoding in encodings:
        try:
            return json.loads(Path(path).read_text(encoding=encoding))
        except UnicodeDecodeError:
            continue
        except json.JSONDecodeError:
            continue
    return {}


def rmtree(path: Path):
    if path.is_file():
        path.unlink()
    elif path.is_dir():
        for child in path.iterdir():
            rmtree(child)
        try:
            path.rmdir()  # nas 的共享盘可能会有残留
        except BaseException:
            ...

def get_addon_name():
    return "AI Node" + get_bl_version()


def _T(word):
    if not isinstance(word, str):
        return word
    import bpy
    from bpy.app.translations import pgettext
    locale = bpy.context.preferences.view.language
    culture = translation.setdefault(locale, {})
    if t := culture.get(word):
        return t

    def f(word):
        culture[word] = pgettext(word)
    Timer.put((f, word))
    return LANG_TEXT.get(locale, {}).get(word, word)


logger.set_translate(_T)


def _T2(word):
    import bpy
    from .translations.translation import REPLACE_DICT
    locale = bpy.context.preferences.view.language
    return REPLACE_DICT.get(locale, {}).get(word, word)


def update_screen():
    try:
        import bpy
        for area in bpy.context.screen.areas:
            area.tag_redraw()
    except BaseException:
        ...


def update_node_editor():
    try:
        import bpy
        for area in bpy.context.screen.areas:
            for space in area.spaces:
                if space.type != "NODE_EDITOR":
                    continue
                space.node_tree = space.node_tree
            if area.type == "NODE_EDITOR":
                area.tag_redraw()
    except Exception:
        ...


def clear_cache(d=None):
    from shutil import rmtree as shutil_rmtree
    if not d:
        clear_cache(Path(__file__).parent)
    else:

        for file in Path(d).iterdir():
            if not file.is_dir():
                continue
            clear_cache(file)
            if file.name == "__pycache__":
                shutil_rmtree(file)


def rgb2hex(r, g, b, *args):
    hex_val = f"#{int(r*256):02x}{int(g*256):02x}{int(b*256):02x}"
    return hex_val


def hex2rgb(hex_val):
    hex_val = hex_val.lstrip('#')
    if len(hex_val) == 3:
        return [int(h, 16) / 16 for h in hex_val]
    return [int(hex_val[i:i + 2], 16) / 256 for i in (0, 2, 4)]


class PrevMgr:
    __PREV__ = {}

    @staticmethod
    def new():
        import bpy.utils.previews
        import random
        prev = bpy.utils.previews.new()
        while (i := random.randint(0, 999999999)) in PrevMgr.__PREV__:
            continue
        PrevMgr.__PREV__[i] = prev
        return prev

    @staticmethod
    def remove(prev):
        import bpy.utils.previews
        bpy.utils.previews.remove(prev)

    @staticmethod
    def clear():
        for prev in PrevMgr.__PREV__.values():
            prev.clear()
            prev.close()
        PrevMgr.__PREV__.clear()


def __del__():
    PrevMgr.clear()


class MetaIn(type):
    def __contains__(cls, name):
        return cls.__contains__(cls, name)


class Icon(metaclass=MetaIn):
    PREV_DICT = PrevMgr.new()
    NONE_IMAGE = ""
    IMG_STATUS = {}
    PIX_STATUS = {}
    PATH2BPY = {}
    ENABLE_HQ_PREVIEW = False
    INSTANCE = None

    def __init__(self) -> None:
        if Icon.NONE_IMAGE and Icon.NONE_IMAGE not in Icon:
            Icon.NONE_IMAGE = FSWatcher.to_str(Icon.NONE_IMAGE)
            self.reg_icon(Icon.NONE_IMAGE)

    def __new__(cls, *args, **kwargs):
        if cls.INSTANCE is None:
            cls.INSTANCE = object.__new__(cls, *args, **kwargs)
        return cls.INSTANCE

    @staticmethod
    def update_path2bpy():
        import bpy
        Icon.PATH2BPY.clear()
        for i in bpy.data.images:
            Icon.PATH2BPY[FSWatcher.to_str(i.filepath)] = i

    @staticmethod
    def apply_alpha(img):
        if img.file_format != "PNG" or img.channels < 4:
            return
        # 预乘alpha 到rgb
        import numpy as np
        pixels = np.zeros(img.size[0] * img.size[1] * 4, dtype=np.float32)
        img.pixels.foreach_get(pixels)
        sized_pixels = pixels.reshape(-1, 4)
        sized_pixels[:, :3] *= sized_pixels[:, 3].reshape(-1, 1)
        img.pixels.foreach_set(pixels)

    @staticmethod
    def clear():
        Icon.PREV_DICT.clear()
        Icon.IMG_STATUS.clear()
        Icon.PIX_STATUS.clear()
        Icon.PATH2BPY.clear()
        Icon.reg_icon(Icon.NONE_IMAGE)

    @staticmethod
    def set_hq_preview():
        from .preference import get_pref
        Icon.ENABLE_HQ_PREVIEW = get_pref().enable_hq_preview

    @staticmethod
    def try_mark_image(path) -> bool:
        p = FSWatcher.to_path(path)
        path = FSWatcher.to_str(path)
        if not p.exists():
            return False
        if Icon.IMG_STATUS.get(path, -1) == p.stat().st_mtime_ns:
            return False
        return True

    @staticmethod
    def can_mark_image(path) -> bool:
        p = FSWatcher.to_path(path)
        path = FSWatcher.to_str(path)
        if not Icon.try_mark_image(p):
            return False
        Icon.IMG_STATUS[path] = p.stat().st_mtime_ns
        return True

    @staticmethod
    def can_mark_pixel(prev, name) -> bool:
        name = FSWatcher.to_str(name)
        if Icon.PIX_STATUS.get(name) == hash(prev.pixels):
            return False
        Icon.PIX_STATUS[name] = hash(prev.pixels)
        return True

    @staticmethod
    def remove_mark(name) -> bool:
        name = FSWatcher.to_str(name)
        Icon.IMG_STATUS.pop(name)
        Icon.PIX_STATUS.pop(name)
        Icon.PREV_DICT.pop(name)
        return True

    @staticmethod
    def reg_none(none: Path):
        none = FSWatcher.to_str(none)
        if none in Icon:
            return
        Icon.NONE_IMAGE = none
        Icon.reg_icon(Icon.NONE_IMAGE)

    @staticmethod
    def reg_icon(path, reload=False):
        path = FSWatcher.to_str(path)
        if not Icon.can_mark_image(path):
            return Icon[path]
        if Icon.ENABLE_HQ_PREVIEW:
            try:
                Icon.reg_icon_hq(path)
            except BaseException:
                Timer.put((Icon.reg_icon_hq, path))
            return Icon[path]
        else:
            if path not in Icon:
                Icon.PREV_DICT.load(path, path, 'IMAGE')
            if reload:
                Timer.put(Icon.PREV_DICT[path].reload)
            return Icon[path]

    @staticmethod
    def reg_icon_hq(path):
        import bpy
        p = FSWatcher.to_path(path)
        path = FSWatcher.to_str(path)
        if path in Icon:
            return
        if p.exists() and p.suffix.lower() in IMG_SUFFIX:
            img = bpy.data.images.load(path)
            Icon.apply_alpha(img)
            Icon.reg_icon_by_pixel(img, path)
            Timer.put((bpy.data.images.remove, img))  # 直接使用 bpy.data.images.remove 会导致卡死

    @staticmethod
    def find_image(path):
        img = Icon.PATH2BPY.get(FSWatcher.to_str(path), None)
        if not img:
            return None
        try:
            _ = img.name  # hack ref detect
            return img
        except ReferenceError:
            Icon.update_path2bpy()
        return None

    @staticmethod
    def load_icon(path):
        import bpy
        p = FSWatcher.to_path(path)
        path = FSWatcher.to_str(path)

        if not Icon.can_mark_image(path):
            return

        # if p.name[:63] in bpy.data.images:
        #     img = bpy.data.images[p.name[:63]]
        #     Icon.update_icon_pixel(img.name, img)
        if img := Icon.find_image(path):
            Icon.update_icon_pixel(path, img)
            return img
        elif p.suffix.lower() in IMG_SUFFIX:
            img = bpy.data.images.load(path)
            img.filepath = path
            Icon.apply_alpha(img)
            Icon.update_path2bpy()
            # img.name = path
            return img

    @staticmethod
    def reg_icon_by_pixel(prev, name):
        name = FSWatcher.to_str(name)
        if not Icon.can_mark_pixel(prev, name):
            return
        if name in Icon:
            return
        p = Icon.PREV_DICT.new(name)
        p.icon_size = (32, 32)
        p.image_size = (prev.size[0], prev.size[1])
        p.image_pixels_float[:] = prev.pixels[:]

    @staticmethod
    def get_icon_id(name: Path):
        p = Icon.PREV_DICT.get(FSWatcher.to_str(name), None)
        if not p:
            p = Icon.PREV_DICT.get(FSWatcher.to_str(Icon.NONE_IMAGE), None)
        return p.icon_id if p else 0

    @staticmethod
    def update_icon_pixel(name, prev):
        """
        更新bpy.data.image 时一并更新(因为pixel 的hash 不变)
        """
        prev.reload()
        p = Icon.PREV_DICT.get(name, None)
        if not p:
            # logger.error("No")
            return
        p.icon_size = (32, 32)
        p.image_size = (prev.size[0], prev.size[1])
        p.image_pixels_float[:] = prev.pixels[:]

    def __getitem__(self, name):
        return Icon.get_icon_id(name)

    def __contains__(self, name):
        return FSWatcher.to_str(name) in Icon.PREV_DICT

    def __class_getitem__(cls, name):
        return cls.__getitem__(cls, name)


class PngParse:

    @staticmethod
    def read_head(pngpath):
        with open(pngpath, 'rb') as f:
            png_header = f.read(25)
            file_sig, ihdr_sig, width, height, bit_depth, color_type, \
                compression_method, filter_method, interlace_method = \
                struct.unpack('>8s4sIIBBBBB', png_header)
            # 输出 PNG 文件头
            data = {
                "PNG file signature": file_sig,
                "IHDR_signature": ihdr_sig,
                "Image_size": [width, height],
                "Bit_depth": bit_depth,
                "Color_type": color_type,
                "Compression_method": compression_method,
                "Filter_method": filter_method,
                "Interlace_method": interlace_method
            }

    @staticmethod
    def read_text_chunk(pngpath) -> dict[str, str]:
        data = {}
        with open(pngpath, 'rb') as file:
            signature = file.read(8)
            if signature != b'\x89PNG\r\n\x1a\n':
                print('Error: Not a PNG file')
                return data

            # IDHR, PLTE, sRGB, tEXt
            while True:
                length_bytes = file.read(4)
                length = struct.unpack('>I', length_bytes)[0]  # Read chunk length (4 bytes)
                chunk_type = file.read(4)      # Read chunk type (4 bytes)
                chunk_data = file.read(length)  # Read chunk data (length bytes)
                crc = file.read(4)             # Read CRC (4 bytes)
                if chunk_type in {b'IHDR', b'PLTE'}:  # header and Palette
                    continue
                elif chunk_type == b'tEXt':
                    keyword, text = chunk_data.decode().split('\0', 1)
                    data[keyword] = text
                elif chunk_type == b'IEND':
                    break
        return data


class PkgInstaller:
    source = [
        "https://mirrors.aliyun.com/pypi/simple/",
        "https://pypi.tuna.tsinghua.edu.cn/simple/",
        "https://pypi.mirrors.ustc.edu.cn/simple/",
        "https://pypi.python.org/simple/",
        "https://pypi.org/simple",
    ]
    fast_url = ""

    @staticmethod
    def select_pip_source():
        if not PkgInstaller.fast_url:
            import requests
            t, PkgInstaller.fast_url = 999, PkgInstaller.source[0]
            for url in PkgInstaller.source:
                try:
                    tping = requests.get(url, timeout=1).elapsed.total_seconds()
                except Exception as e:
                    logger.warning(e)
                    continue
                if tping < 0.1:
                    PkgInstaller.fast_url = url
                    break
                if tping < t:
                    t, PkgInstaller.fast_url = tping, url
        return PkgInstaller.fast_url

    @staticmethod
    def is_installed(package):
        import importlib
        try:
            return importlib.import_module(package)
        except ModuleNotFoundError:
            return False

    @staticmethod
    def prepare_pip():
        import ensurepip
        if PkgInstaller.is_installed("pip"):
            return True
        try:
            ensurepip.bootstrap()
            return True
        except BaseException:
            ...
        return False

    @staticmethod
    def try_install(*packages):
        if not PkgInstaller.prepare_pip():
            return False
        need = [pkg for pkg in packages if not PkgInstaller.is_installed(pkg)]
        from pip._internal import main
        if need:
            url = PkgInstaller.select_pip_source()
        for pkg in need:
            try:
                site = urlparse(url)
                # 避免build
                command = ['install', pkg, "-i", url, "--prefer-binary"]
                command.append("--trusted-host")
                command.append(site.netloc)
                main(command)
                if not PkgInstaller.is_installed(pkg):
                    return False
            except Exception:
                return False
        return True


class FSWatcher:
    """
    监听文件/文件夹变化的工具类
        register: 注册监听, 传入路径和回调函数(可空)
        unregister: 注销监听
        run: 监听循环, 使用单例,只在第一次初始化时调用
        stop: 停止监听, 释放资源
        consume_change: 消费变化, 当监听对象发生变化时记录为changed, 主动消费后置False, 用于自定义回调函数
    """
    _watcher_path: dict[Path, bool] = {}
    _watcher_stat = {}
    _watcher_callback = {}
    _watcher_queue = queue.Queue()
    _running = False

    @staticmethod
    def init() -> None:
        FSWatcher._run()

    @staticmethod
    def register(path, callback=None):
        path = FSWatcher.to_path(path)
        if path in FSWatcher._watcher_path:
            return
        FSWatcher._watcher_path[path] = False
        FSWatcher._watcher_callback[path] = callback

    @staticmethod
    def unregister(path):
        path = FSWatcher.to_path(path)
        FSWatcher._watcher_path.pop(path)
        FSWatcher._watcher_callback.pop(path)

    @staticmethod
    def _run():
        if FSWatcher._running:
            return
        FSWatcher._running = True
        Thread(target=FSWatcher._loop, daemon=True).start()
        Thread(target=FSWatcher._run_ex, daemon=True).start()

    @staticmethod
    def _run_ex():
        while FSWatcher._running:
            try:
                path = FSWatcher._watcher_queue.get(timeout=0.1)
                if path not in FSWatcher._watcher_path:
                    continue
                if callback := FSWatcher._watcher_callback[path]:
                    callback(path)
            except queue.Empty:
                pass

    @staticmethod
    def _loop():
        """
            监听所有注册的路径, 有变化时记录为changed
        """
        while FSWatcher._running:
            # list() avoid changed while iterating
            for path, changed in list(FSWatcher._watcher_path.items()):
                if changed:
                    continue
                if not path.exists():
                    continue
                mtime = path.stat().st_mtime_ns
                if FSWatcher._watcher_stat.get(path, None) == mtime:
                    continue
                FSWatcher._watcher_stat[path] = mtime
                FSWatcher._watcher_path[path] = True
                FSWatcher._watcher_queue.put(path)
            time.sleep(0.5)

    @staticmethod
    def stop():
        FSWatcher._watcher_queue.put(None)
        FSWatcher._running = False

    @staticmethod
    def consume_change(path) -> bool:
        path = FSWatcher.to_path(path)
        if path in FSWatcher._watcher_path and FSWatcher._watcher_path[path]:
            FSWatcher._watcher_path[path] = False
            return True
        return False

    @lru_cache
    @staticmethod
    def get_nas_mapping():
        if platform.system() != "Windows":
            return {}
        import subprocess
        result = subprocess.run("net use", capture_output=True, text=True, encoding="gbk", check=True)
        if result.returncode != 0 or result.stdout is None:
            return {}
        nas_mapping = {}
        try:
            lines = result.stdout.strip().split("\n")[4:]
            for line in lines:
                columns = line.split()
                if len(columns) < 3:
                    continue
                local_drive = columns[1] + "/"
                nas_path = Path(columns[2]).resolve().as_posix()
                nas_mapping[local_drive] = nas_path
        except Exception:
            ...
        return nas_mapping

    @lru_cache(maxsize=1024)
    @staticmethod
    def to_str(path: Path):
        p = Path(path)
        try:
            res_str = p.resolve().as_posix()
        except FileNotFoundError as e:
            res_str = p.as_posix()
            logger.warning(e)
        # 处理nas路径
        for local_drive, nas_path in FSWatcher.get_nas_mapping().items():
            if not res_str.startswith(nas_path):
                continue
            return res_str.replace(nas_path, local_drive)
        return res_str

    @lru_cache(maxsize=1024)
    @staticmethod
    def to_path(path: Path):
        return Path(path)


class ScopeTimer:
    def __init__(self, name: str = "", prt=print):
        self.name = name
        self.time_start = time.time()
        self.echo = prt

    def __del__(self):
        self.echo(f"{self.name} cost {time.time() - self.time_start:.4f}s")


class CtxTimer:
    def __init__(self, name: str = "", prt=print):
        self.name = name
        self.time_start = time.time()
        self.echo = prt

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.echo(f"{self.name} cost {time.time() - self.time_start:.4f}s")
