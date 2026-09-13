from pathlib import Path


APP = Path(__file__).resolve().parents[1] / 'app.py'


def main() -> None:
    text = APP.read_text(encoding='utf-8')
    old = "    images = [x for x in list_images(project_id) if str(x.get('id')) in wanted]"
    new = "    images = [x for x in load_images(project_id) if str(x.get('id')) in wanted]"
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f'v52 review owner: expected exactly one live source match, found {count}')
    APP.write_text(text.replace(old, new, 1), encoding='utf-8')


if __name__ == '__main__':
    main()
