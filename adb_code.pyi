class CodeError(Exception):
    ...

def adb_v1(code: int) -> int:
    """生成 ADB v1 校验码"""
    ...

def adb_v2(code: int) -> int:
    """生成 ADB v2 校验码"""
    ...

def zj_v1(code: int) -> int:
    """生成自检 v1 校验码"""
    ...

def zj_v2(code: int) -> int:
    """生成自检 v2 校验码"""
    ...

def auto_adb(code: int) -> int:
    """自动选择版本并生成 ADB 校验码"""
    ...

def auto_zj(code: int) -> int:
    """自动选择版本并生成自检校验码"""
    ...