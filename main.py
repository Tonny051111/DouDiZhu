"""运行：python main.py ；仅首次需要 python -m pip install -r requirements.txt。"""
from pathlib import Path
import logging
import sys


def main():
    log_path = Path(__file__).resolve().with_name("三人经典斗地主.log")
    logging.basicConfig(filename=log_path, level=logging.INFO, encoding="utf-8",
                        format="%(asctime)s %(levelname)s %(message)s")
    app = None
    try:
        from app import App
        app = App()
        logging.info("三人经典斗地主 1.1 启动；字体=%s；音效可用=%s", app.font_path, app.audio.available)
        app.run()
    except ModuleNotFoundError as error:
        logging.exception("依赖缺失")
        print(f"缺少依赖：{error.name}\n请先运行：python -m pip install -r requirements.txt")
        return 1
    except Exception as error:
        logging.exception("运行异常")
        print(f"三人经典斗地主遇到问题：{error}\n日志：{log_path}")
        return 1
    finally:
        if app:
            app.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
