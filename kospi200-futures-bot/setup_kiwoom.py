"""
키움 OpenAPI+ 설치 상태 점검 및 환경 검증.

실행:
    python setup_kiwoom.py

이 스크립트는 OpenAPI+ 설치 없이도 실행 가능하며,
설치 상태와 환경 요구사항을 점검한다.
"""

import sys
import platform
import struct
import winreg
from loguru import logger

logger.remove()
logger.add(sys.stdout, format="<green>{time:HH:mm:ss}</green> | <level>{level}</level> | {message}")


def check_python_arch():
    bits = struct.calcsize("P") * 8
    if bits == 32:
        logger.info(f"[PASS] Python 아키텍처: {bits}bit (키움 OpenAPI+ 호환)")
    else:
        logger.warning(f"[WARN] Python 아키텍처: {bits}bit")
        logger.warning("  → 키움 OpenAPI+는 32bit Python 권장")
        logger.warning("  → 경로: https://www.python.org/downloads/windows/")
        logger.warning("  → 'Windows installer (32-bit)' 선택")
    return bits


def check_python_version():
    v = sys.version_info
    if v >= (3, 8):
        logger.info(f"[PASS] Python 버전: {v.major}.{v.minor}.{v.micro}")
    else:
        logger.error(f"[FAIL] Python 버전: {v.major}.{v.minor} (3.8 이상 필요)")
    return v


def check_packages():
    required = {
        "PyQt5": "5.15",
        "pandas": "1.5",
        "numpy": "1.23",
        "yaml": "6.0",
        "loguru": "0.7",
        "win32api": None,
    }
    all_ok = True
    for pkg, min_ver in required.items():
        try:
            if pkg == "yaml":
                import yaml
                ver = yaml.__version__
            elif pkg == "win32api":
                import win32api
                ver = "OK"
            else:
                mod = __import__(pkg)
                ver = getattr(mod, "__version__", "OK")
            logger.info(f"[PASS] {pkg}: {ver}")
        except ImportError:
            logger.error(f"[FAIL] {pkg} 미설치 → pip install {pkg}")
            all_ok = False
    return all_ok


def check_kiwoom_com():
    try:
        key = winreg.OpenKey(winreg.HKEY_CLASSES_ROOT, "OpenAPI.KHOpenAPI.1")
        winreg.CloseKey(key)
        logger.info("[PASS] 키움 OpenAPI+ COM 등록 확인")
        return True
    except FileNotFoundError:
        logger.error("[FAIL] 키움 OpenAPI+ 미설치")
        logger.error("")
        logger.error("  ▶ 설치 방법:")
        logger.error("  1. 키움증권 홈페이지 접속")
        logger.error("     https://www1.kiwoom.com/nkw.templateFrameSet.do?m=m1408000000")
        logger.error("  2. [Open API+ 다운로드] 클릭 → OpenAPISetup.exe 실행")
        logger.error("  3. 설치 완료 후 HTS(영웅문) 실행 → 로그인")
        logger.error("  4. 상단 메뉴 [계좌] → [모의투자] → 모의투자 신청")
        logger.error("  5. 이 스크립트 재실행")
        return False


def check_hts_running():
    """HTS(영웅문) 실행 여부 확인."""
    try:
        import psutil
        for proc in psutil.process_iter(["name"]):
            if "hts" in proc.info["name"].lower():
                logger.info(f"[PASS] HTS 실행 중: {proc.info['name']}")
                return True
        logger.warning("[WARN] HTS(영웅문) 미실행 — OpenAPI+ 사용 시 불필요할 수 있음")
        return False
    except ImportError:
        logger.info("[SKIP] psutil 없음 - HTS 실행 여부 확인 생략")
        return None


def main():
    logger.info("=" * 55)
    logger.info("  키움 OpenAPI+ 환경 점검")
    logger.info("=" * 55)

    logger.info("")
    logger.info("── Python 환경 ──")
    bits = check_python_arch()
    check_python_version()

    logger.info("")
    logger.info("── 패키지 설치 상태 ──")
    pkg_ok = check_packages()

    logger.info("")
    logger.info("── 키움 OpenAPI+ ──")
    kiwoom_ok = check_kiwoom_com()

    logger.info("")
    logger.info("── HTS ──")
    check_hts_running()

    logger.info("")
    logger.info("=" * 55)
    if kiwoom_ok and pkg_ok:
        logger.info("  환경 준비 완료! 다음 단계:")
        logger.info("  1. config.yaml → 계좌번호 입력")
        logger.info("  2. python test_connection.py  (모의투자 연결 테스트)")
        logger.info("  3. python main.py             (봇 실행)")
    else:
        logger.warning("  위 [FAIL] 항목 해결 후 재실행하세요.")
    logger.info("=" * 55)


if __name__ == "__main__":
    main()
