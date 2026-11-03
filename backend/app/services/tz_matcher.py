"""Сверка объектов из ТЗ с файлами, изменёнными в MR.

Объект ТЗ — это файл репозитория. Значим «хвост» пути: например, объект
`AC_FIN\\RECALC_COMM.plp` совпадает с файлом `src/AC_FIN/RECALC_COMM.plp`.
Сравнение регистронезависимое, разделители `\\` и `/` равнозначны.
"""
import fnmatch


def normalize_parts(path):
    if not path:
        return []
    parts = path.replace("\\", "/").strip().strip("/").split("/")
    return [p.strip().casefold() for p in parts if p.strip()]


def tail_matches(object_name, file_path):
    obj = normalize_parts(object_name)
    file_parts = normalize_parts(file_path)
    if not obj or len(obj) > len(file_parts):
        return False
    return file_parts[-len(obj):] == obj


def is_ignored(path, patterns):
    name = path.replace("\\", "/").split("/")[-1]
    full = path.replace("\\", "/")
    return any(fnmatch.fnmatch(name, p) or fnmatch.fnmatch(full, p) for p in patterns)


def match_objects(tz_objects, mr_files, ignore_patterns=()):
    """
    tz_objects: [{id, system_name, display_name, change_description}]
    mr_files:   [{id, old_path, new_path, change_type}]
    Возвращает dict:
      matched:  [{object, file_id, path}]
      missing:  [object]  — есть в ТЗ, но не изменён в MR (справочно, ошибкой не считается)
      extra:    [{file_id, path}] — изменён в MR, но нет в ТЗ
      ignored:  [{file_id, path}] — служебные файлы, не участвуют в сверке
      file_status: {file_id: (status, object_id)}
      ok: bool
    """
    matched, missing, extra, ignored = [], [], [], []
    file_status = {}
    used_files = set()

    for obj in tz_objects:
        hit = None
        for f in mr_files:
            paths = [p for p in (f.get("new_path"), f.get("old_path")) if p]
            if any(tail_matches(obj["system_name"], p) for p in paths):
                hit = f
                break
        if hit:
            path = hit.get("new_path") or hit.get("old_path")
            matched.append({"object": obj, "file_id": hit["id"], "path": path,
                            "change_type": hit.get("change_type")})
            used_files.add(hit["id"])
            file_status[hit["id"]] = ("matched", obj.get("id"))
        else:
            missing.append(obj)

    for f in mr_files:
        if f["id"] in used_files:
            continue
        path = f.get("new_path") or f.get("old_path")
        if is_ignored(path, ignore_patterns):
            ignored.append({"file_id": f["id"], "path": path})
            file_status[f["id"]] = ("ignored", None)
        else:
            extra.append({"file_id": f["id"], "path": path, "change_type": f.get("change_type")})
            file_status[f["id"]] = ("extra", None)

    return {
        "matched": matched,
        "missing": missing,
        "extra": extra,
        "ignored": ignored,
        "file_status": file_status,
        "ok": not extra,
    }


def extract_ticket_key(regex, *texts):
    import re

    pattern = re.compile(rf"(?<![A-Za-z0-9]){regex}(?![0-9])")
    for text in texts:
        if not text:
            continue
        m = pattern.search(text)
        if m:
            return m.group(0).upper()
        # в именах веток регистр часто нижний: feature/rck2-3232-...
        m = re.compile(rf"(?<![A-Za-z0-9]){regex}(?![0-9])", re.IGNORECASE).search(text)
        if m:
            return m.group(0).upper()
    return None
