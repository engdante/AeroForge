"""
report.py — отчети: Markdown, HTML и BOM (CSV).

Отчетът е самостоятелен (inline CSS, без външни ресурси) и се записва в
exports/<дизайн>/ заедно с design.json.
"""

import csv
import datetime
import html
import io
import json
import os
import re

DISCLAIMER = (
    "Този отчет е изчислен с емпирични модели за RC моделизъм и НЕ е "
    "сертификационно изчисление. Преди първия полет: провери центъра на "
    "тежестта на реалния модел, направи статично изпитание на крилото "
    "(натоварване ~3× полетното), ограничи хода на кормилата и спазвай "
    "изискванията за безопасност на мястото за летене."
)


def _f(value, digits=1):
    """Форматира число с фиксирани знаци (без 'None')."""
    if value is None:
        return "—"
    try:
        return ("%." + str(digits) + "f") % float(value)
    except (TypeError, ValueError):
        return str(value)


def _timestamp():
    return datetime.datetime.now().strftime("%d.%m.%Y %H:%M")


def slugify(name):
    """Превръща името на дизайна в безопасно име на папка."""
    text = str(name or "design").strip()
    text = re.sub(r"[<>:\"/\\|?*]+", "_", text)
    text = re.sub(r"\s+", "_", text)
    return text.strip("._")[:50] or "design"


def build_bom_csv(res):
    """BOM (списък на материалите) като CSV текст."""
    buf = io.StringIO()
    writer = csv.writer(buf, delimiter=";", lineterminator="\r\n")
    writer.writerow(["#", "Компонент", "Категория", "Брой",
                     "Ед. маса (g)", "Общо (g)", "Позиция X (mm)",
                     "Оценка", "Бележка"])
    for i, c in enumerate(res["weights"]["components"], 1):
        writer.writerow([
            i, c["name"], c.get("category_label", ""), c["qty"],
            _f(c["unit_mass_g"], 1), _f(c["mass_g"], 1),
            _f(c.get("x_mm"), 0),
            "оценка" if c.get("estimated") else "зададено",
            c.get("note", ""),
        ])
    writer.writerow([])
    writer.writerow(["", "Конструкция (печат)", "", "", "",
                     _f(res["weights"]["airframe_g"], 1), "", "оценка", ""])
    writer.writerow(["", "ОБЩО", "", "", "",
                     _f(res["weights"]["total_g"], 1), "", "", ""])
    writer.writerow([])
    writer.writerow(["#", "Печатана част", "Брой", "Обем (cm³)",
                     "Маса (g)", "Филамент (m)", "Време (h)", "Цена (€)"])
    for i, p in enumerate(res["print"]["parts"], 1):
        writer.writerow([
            i, p["name"], p["pieces"], _f(p["volume_cm3"], 1),
            _f(p["mass_g"], 1), _f(p["filament_m"], 1),
            _f(p["time_h"], 1), _f(p["cost"], 2),
        ])
    return buf.getvalue()


def build_report_markdown(res):
    """Пълен отчет в Markdown."""
    g = res["geometry"]
    a = res["aero"]
    w = res["weights"]
    s = res["stability"]
    p = res["propulsion"]
    st = res["structure"]
    pr = res["print"]
    bat = p["battery"]
    tail = g["tail"]

    lines = []
    add = lines.append
    add("# AeroForge — „%s“" % res["inputs"]["name"])
    add("")
    add("_Изготвен: %s · AeroForge %s · тип: %s_"
        % (_timestamp(), res["version"], res["mission"]["label"]))
    add("")
    add("## 1. Обобщение")
    add("")
    add("| Показател | Стойност |")
    add("|---|---|")
    add("| Обща маса | **%s g** |" % _f(w["total_g"], 0))
    add("| Размах | **%s mm** |" % _f(g["span_mm"], 0))
    add("| Площ на крилото | %s dm² |" % _f(g["area_dm2"], 1))
    add("| Натоварване на крилото | %s g/dm² |"
        % _f(g["wing_loading_g_dm2"], 1))
    add("| Коренов / върхов хорд | %s / %s mm |"
        % (_f(g["c_root_mm"], 0), _f(g["c_tip_mm"], 0)))
    add("| Средна аеродинамична хорда | %s mm |" % _f(g["mac_mm"], 0))
    add("| Скорост на загуба на подемна сила | %s m/s |"
        % _f(a["v_stall_ms"], 1))
    add("| Крейсерска скорост | %s m/s (%s km/h) |"
        % (_f(a["v_cruise_ms"], 1), _f(a["v_cruise_kmh"], 0)))
    add("| Тяга : тегло | %s : 1 |" % _f(p["thrust_to_weight_actual"], 2))
    add("| Време на полет (крейсер) | ~%s мин |"
        % _f(bat["endurance_min"], 0))
    add("| ЦТ | %s %% MAC |" % _f(s["cg_pct_mac"], 1))
    add("| Статичен запас | %s %% MAC |" % _f(s["static_margin_pct"], 1))
    add("| Маса на печата | %s g (%s %%) |"
        % (_f(w["airframe_g"], 0), _f(w["airframe_pct"], 0)))
    add("| Печат: време / филамент / цена | %s h / %s g / %s € |"
        % (_f(pr["time_h"], 1), _f(pr["total_mass_g"], 0),
           _f(pr["cost"], 0)))
    add("")

    add("## 2. Товар и маси")
    add("")
    add("| Компонент | Категория | Бр. | Ед. (g) | Общо (g) | X (mm) |")
    add("|---|---|---|---|---|---|")
    for c in w["components"]:
        add("| %s%s | %s | %s | %s | %s | %s |"
            % (c["name"], " _(оценка)_" if c.get("estimated") else "",
               c.get("category_label", ""), _f(c["qty"], 0),
               _f(c["unit_mass_g"], 1), _f(c["mass_g"], 1),
               _f(c.get("x_mm"), 0)))
    add("| _Конструкция (печат)_ | — | — | — | %s | — |"
        % _f(w["airframe_g"], 1))
    add("| **Общо** | | | | **%s** | |" % _f(w["total_g"], 1))
    add("")
    add("Разбивка по категории:")
    add("")
    for b in w["breakdown"]:
        add("- %s — %s g (%s %%)"
            % (b["name"], _f(b["mass_g"], 0), _f(b["pct"], 0)))
    add("")

    add("## 3. Крило и аеродинамика")
    add("")
    add("- Профил: **%s** (%s)"
        % (g["airfoil"]["name"], g["airfoil"]["use"]))
    add("- Относително разтежение: %s, свиване: %s, диаедър: %s°"
        % (_f(g["aspect_ratio"], 1), _f(g["taper"], 2),
           _f(g["dihedral_deg"], 1)))
    add("- CL_max: %s (каталожно %s) при Re %s"
        % (_f(a["cl_max"], 2), _f(a["cl_max_catalog"], 2),
           _f(a["re_cruise"], 0)))
    add("- L/D max: %s при CL = %s"
        % (_f(a["ld_max"], 1), _f(a["cl_at_ld_max"], 2)))
    add("- CD0: %s, Oswald e: %s" % (_f(a["cd0"], 3), _f(a["oswald"], 2)))
    add("- Нужна мощност в крейсер: %s W" % _f(a["power_required_w"], 0))
    add("")

    add("## 4. Опашка и център на тежестта")
    add("")
    if res["mission"]["has_tail"]:
        add("- Хоризонтална опашка: %s dm² (V_h = %s), рамо %s mm"
            % (_f(tail["s_h_dm2"], 1), _f(tail["vh"], 2),
               _f(tail["l_h_mm"], 0)))
        add("- Вертикална опашка: %s dm² (V_v = %s), рамо %s mm"
            % (_f(tail["s_v_dm2"], 1), _f(tail["vv"], 3),
               _f(tail["l_v_mm"], 0)))
    else:
        add("- Крило без опашка (elevoni)")
    add("- ЦТ: %s mm от носа (%s %% MAC)"
        % (_f(s["x_cg_mm"], 0), _f(s["cg_pct_mac"], 1)))
    add("- Аеродинамичен център: %s mm; целеви ЦТ: %s mm"
        % (_f(s["x_ac_mm"], 0), _f(s["x_target_mm"], 0)))
    if s.get("battery_x_required_mm") is not None:
        add("- **Постави батерията на %s mm от носа** (по подразбиране %s mm)"
            % (_f(s["battery_x_required_mm"], 0),
               _f(s["battery_x_default_mm"], 0)))
    add("- Водещ ръб на крилото: %s mm (препоръка: %s mm)"
        % (_f(g["wing_le_mm"], 0), _f(g.get("wing_le_recommended_mm"), 0)))
    add("")

    add("## 5. Задвижване")
    add("")
    add("- Максимална мощност: %s W (на вала %s W)"
        % (_f(p["p_max_elec_w"], 0), _f(p["p_max_shaft_w"], 0)))
    add("- Тяга (статична): %s N ≈ %s kg"
        % (_f(p["thrust_avail_n"], 1), _f(p["thrust_avail_kg"], 2)))
    add("- Витло: %d×%d инча, ~%s об/мин, мотор Kv ≈ %s"
        % (p["prop_d_in"], p["prop_pitch_in"], _f(p["rpm_target"], 0),
           _f(p["kv"], 0)))
    add("- Максимален ток: %s A → ESC **%d A**"
        % (_f(p["i_max_a"], 1), p["esc_a"]))
    add("- Батерия: %dS %s mAh (%s Wh), нужни %sC, маса %s g"
        % (bat["cells"], _f(bat["capacity_mah"], 0),
           _f(bat["energy_wh"], 1), _f(bat["c_rating_needed"], 0),
           _f(bat["mass_g"], 0)))
    add("- Време на полет: ~%s мин (при 80 %% използваем заряд)"
        % _f(bat["endurance_min"], 0))
    add("")

    add("## 6. Якост на крилото")
    add("")
    add("- Работно натоварване: %s g, коефициент на сигурност %s"
        % (_f(st["n_limit"], 1), _f(st["safety_factor"], 2)))
    add("- Коренов момент: %s N·m (граничен %s N·m)"
        % (_f(st["m_root_nm"], 1), _f(st["m_ult_nm"], 1)))
    add("- Височина на спаровия пояс: %s mm" % _f(st["spar_height_mm"], 1))
    add("- Нужна площ на капсите: %s mm² (печатани: %s mm²)"
        % (_f(st["cap_area_req_mm2"], 1), _f(st["cap_area_print_mm2"], 1)))
    add("- Решение: **%s**" % st["solution"])
    if st["carbon_required"]:
        add("- Карбон: лента %.0f×%.1f mm × %d на капс"
            % (st["carbon"]["width_mm"], st["carbon"]["thickness_mm"],
               st["carbon"]["count"]))
    add("- Съединителна тръба: ⌀%s×%s mm, дължина %s mm × %d"
        % (_f(st["joiner_tube"]["od_mm"], 1),
           _f(st["joiner_tube"]["id_mm"], 1),
           _f(st["joiner_tube"]["length_mm"], 0),
           st["joiner_tube"]["count"]))
    add("- Деформация на върха: %s mm (лимит %s mm)"
        % (_f(st["deflection_carbon_mm"] if st["carbon_required"]
              else st["deflection_print_mm"], 1),
           _f(st["deflection_limit_mm"], 1)))
    add("")

    add("## 7. Печат")
    add("")
    add("- Филамент: **%s** (%s g/cm³, %s €/kg)"
        % (res["filament"]["name"],
           _f(res["filament"]["printed_density"], 2),
           _f(res["filament"]["price_per_kg"], 0)))
    add("- Дюза %s mm, %s периметъра, %s %% infill, слоеве %s mm"
        % (_f(res["resolved"]["nozzle"], 2),
           res["resolved"]["perimeters"], _f(res["resolved"]["infill"], 0),
           _f(res["resolved"]["layer_height"], 2)))
    add("")
    add("| Част | Брой | Обем (cm³) | Маса (g) | Филамент (m) | Време (h) |")
    add("|---|---|---|---|---|---|")
    for part in pr["parts"]:
        add("| %s | %d | %s | %s | %s | %s |"
            % (part["name"], part["pieces"], _f(part["volume_cm3"], 1),
               _f(part["mass_g"], 0), _f(part["filament_m"], 1),
               _f(part["time_h"], 1)))
    add("| **Общо** | **%d** | | **%s** | **%s** | **%s** |"
        % (pr["pieces"], _f(pr["total_mass_g"], 0),
           _f(pr["filament_m"], 1), _f(pr["time_h"], 1)))
    add("")
    add("Сравнение на филаментите при същия обем:")
    add("")
    add("| Филамент | Маса (g) | Цена (€) |")
    add("|---|---|---|")
    for fc in w["filament_comparison"]:
        add("| %s | %s | %s |" % (fc["name"], _f(fc["mass_g"], 0),
                                  _f(fc["cost"], 0)))
    add("")

    add("## 8. Проверки")
    add("")
    icons = {"ok": "✅", "info": "ℹ️", "warn": "⚠️", "error": "❌"}
    for c in res["checks"]:
        add("- %s **%s** — %s" % (icons.get(c["level"], "•"),
                                  c["title"], c["detail"]))
    add("")
    add("## 9. Забележка")
    add("")
    add(DISCLAIMER)
    add("")
    return "\n".join(lines)


_CSS = """
body{font-family:'Segoe UI',Tahoma,sans-serif;background:#14181f;color:#dfe5ee;
     margin:0;padding:28px;line-height:1.5}
.wrap{max-width:1000px;margin:0auto}
h1{font-size:26px;margin:0 0 4px;color:#eaf2ff}
h2{font-size:18px;margin:28px 0 10px;border-bottom:1px solid #2b3444;
   padding-bottom:6px;color:#8fd3ff}
.sub{color:#8ea0b8;font-size:13px;margin-bottom:18px}
table{border-collapse:collapse;width:100%;margin:8px 0 16px;font-size:13px}
th,td{border:1px solid #2b3444;padding:6px 9px;text-align:left}
th{background:#1c2431;color:#a9c1dd}
tr:nth-child(even) td{background:#171d26}
ul{margin:6px 0 16px 18px;padding:0}
li{margin:3px 0}
.ok{color:#5fd787}.info{color:#7fb2ff}.warn{color:#f0c04a}.error{color:#ff7a7a}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));
      gap:10px;margin:12px 0 20px}
.card{background:#1a2230;border:1px solid #2b3444;border-radius:8px;
      padding:10px 12px}
.card .k{font-size:11px;color:#8ea0b8;text-transform:uppercase;
         letter-spacing:.04em}
.card .v{font-size:19px;color:#eaf2ff;margin-top:2px}
.note{background:#1a2230;border-left:3px solid #f0c04a;padding:10px 14px;
      font-size:12px;color:#b9c6d8;margin-top:24px}
"""


def _esc(text):
    return html.escape(str(text if text is not None else ""))


def _table(headers, rows):
    out = ["<table><tr>"]
    out.extend("<th>%s</th>" % _esc(h) for h in headers)
    out.append("</tr>")
    for row in rows:
        out.append("<tr>")
        out.extend("<td>%s</td>" % _esc(c) for c in row)
        out.append("</tr>")
    out.append("</table>")
    return "".join(out)


def build_report_html(res):
    """Самостоятелен HTML отчет (тъмна тема, без външни ресурси)."""
    g = res["geometry"]
    a = res["aero"]
    w = res["weights"]
    s = res["stability"]
    p = res["propulsion"]
    st = res["structure"]
    pr = res["print"]
    bat = p["battery"]

    cards = [
        ("Обща маса", "%s g" % _f(w["total_g"], 0)),
        ("Размах", "%s mm" % _f(g["span_mm"], 0)),
        ("Площ", "%s dm²" % _f(g["area_dm2"], 1)),
        ("Натоварване", "%s g/dm²" % _f(g["wing_loading_g_dm2"], 1)),
        ("V_stall", "%s m/s" % _f(a["v_stall_ms"], 1)),
        ("Тяга : тегло", "%s : 1" % _f(p["thrust_to_weight_actual"], 2)),
        ("Време на полет", "~%s мин" % _f(bat["endurance_min"], 0)),
        ("ЦТ", "%s %% MAC" % _f(s["cg_pct_mac"], 1)),
        ("Печат", "%s g / %s h" % (_f(w["airframe_g"], 0),
                                   _f(pr["time_h"], 1))),
    ]

    parts = []
    parts.append("<h1>AeroForge — „%s“</h1>" % _esc(res["inputs"]["name"]))
    parts.append('<div class="sub">%s · AeroForge %s · %s</div>'
                 % (_timestamp(), _esc(res["version"]),
                    _esc(res["mission"]["label"])))
    parts.append('<div class="grid">')
    for k, v in cards:
        parts.append('<div class="card"><div class="k">%s</div>'
                     '<div class="v">%s</div></div>' % (_esc(k), _esc(v)))
    parts.append("</div>")

    parts.append("<h2>Товар и маси</h2>")
    rows = []
    for c in w["components"]:
        rows.append([c["name"] + (" (оценка)" if c.get("estimated") else ""),
                     c.get("category_label", ""), _f(c["qty"], 0),
                     _f(c["unit_mass_g"], 1), _f(c["mass_g"], 1),
                     _f(c.get("x_mm"), 0)])
    rows.append(["Конструкция (печат)", "—", "—", "—",
                 _f(w["airframe_g"], 1), "—"])
    rows.append(["ОБЩО", "", "", "", _f(w["total_g"], 1), ""])
    parts.append(_table(["Компонент", "Категория", "Бр.", "Ед. (g)",
                         "Общо (g)", "X (mm)"], rows))

    parts.append("<h2>Крило, опашка и ЦТ</h2><ul>")
    parts.append("<li>Профил: <b>%s</b> — %s</li>"
                 % (_esc(g["airfoil"]["name"]), _esc(g["airfoil"]["use"])))
    parts.append("<li>Коренов / върхов хорд: %s / %s mm, MAC %s mm</li>"
                 % (_f(g["c_root_mm"], 0), _f(g["c_tip_mm"], 0),
                    _f(g["mac_mm"], 0)))
    parts.append("<li>AR %s, свиване %s, диаедър %s°</li>"
                 % (_f(g["aspect_ratio"], 1), _f(g["taper"], 2),
                    _f(g["dihedral_deg"], 1)))
    if res["mission"]["has_tail"]:
        parts.append("<li>Хоризонтална опашка %s dm², вертикална %s dm²</li>"
                     % (_f(g["tail"]["s_h_dm2"], 1),
                        _f(g["tail"]["s_v_dm2"], 1)))
    parts.append("<li>ЦТ %s mm от носа (%s %% MAC), статичен запас %s %%</li>"
                 % (_f(s["x_cg_mm"], 0), _f(s["cg_pct_mac"], 1),
                    _f(s["static_margin_pct"], 1)))
    if s.get("battery_x_required_mm") is not None:
        parts.append("<li><b>Батерия на %s mm от носа</b> (по подразбиране "
                     "%s mm)</li>"
                     % (_f(s["battery_x_required_mm"], 0),
                        _f(s["battery_x_default_mm"], 0)))
    parts.append("<li>Водещ ръб на крилото: %s mm (препоръка %s mm)</li>"
                 % (_f(g["wing_le_mm"], 0),
                    _f(g.get("wing_le_recommended_mm"), 0)))
    parts.append("</ul>")

    parts.append("<h2>Задвижване</h2><ul>")
    parts.append("<li>Мощност %s W, тяга %s N (%s kg)</li>"
                 % (_f(p["p_max_elec_w"], 0), _f(p["thrust_avail_n"], 1),
                    _f(p["thrust_avail_kg"], 2)))
    parts.append("<li>Витло %d×%d инча, ~%s об/мин, Kv ≈ %s</li>"
                 % (p["prop_d_in"], p["prop_pitch_in"],
                    _f(p["rpm_target"], 0), _f(p["kv"], 0)))
    parts.append("<li>Ток %s A → ESC %d A; батерия %dS %s mAh (%s Wh), "
                 "%sC</li>"
                 % (_f(p["i_max_a"], 1), p["esc_a"], bat["cells"],
                    _f(bat["capacity_mah"], 0), _f(bat["energy_wh"], 1),
                    _f(bat["c_rating_needed"], 0)))
    parts.append("</ul>")

    parts.append("<h2>Якост</h2><ul>")
    parts.append("<li>M_корен %s N·m при %s g, SF %s</li>"
                 % (_f(st["m_root_nm"], 1), _f(st["n_limit"], 1),
                    _f(st["safety_factor"], 2)))
    parts.append("<li>Капси: нужни %s mm², печатани %s mm² → <b>%s</b></li>"
                 % (_f(st["cap_area_req_mm2"], 1),
                    _f(st["cap_area_print_mm2"], 1), _esc(st["solution"])))
    if st["carbon_required"]:
        parts.append("<li>Карбон: %.0f×%.1f mm × %d на капс</li>"
                     % (st["carbon"]["width_mm"],
                        st["carbon"]["thickness_mm"],
                        st["carbon"]["count"]))
    parts.append("</ul>")

    parts.append("<h2>Печат</h2>")
    rows = []
    for part in pr["parts"]:
        rows.append([part["name"], part["pieces"],
                     _f(part["volume_cm3"], 1), _f(part["mass_g"], 0),
                     _f(part["filament_m"], 1), _f(part["time_h"], 1),
                     _f(part["cost"], 2)])
    rows.append(["ОБЩО", pr["pieces"], "", _f(pr["total_mass_g"], 0),
                 _f(pr["filament_m"], 1), _f(pr["time_h"], 1),
                 _f(pr["cost"], 2)])
    parts.append(_table(["Част", "Бр.", "Обем (cm³)", "Маса (g)",
                         "Филамент (m)", "Време (h)", "Цена (€)"], rows))

    parts.append("<h2>Проверки</h2><ul>")
    for c in res["checks"]:
        parts.append('<li class="%s"><b>%s</b> — %s</li>'
                     % (_esc(c["level"]), _esc(c["title"]),
                        _esc(c["detail"])))
    parts.append("</ul>")
    parts.append('<div class="note">%s</div>' % _esc(DISCLAIMER))

    return ('<!DOCTYPE html><html lang="bg"><head><meta charset="utf-8">'
            "<title>AeroForge — %s</title><style>%s</style></head><body>"
            '<div class="wrap">%s</div></body></html>'
            % (_esc(res["inputs"]["name"]), _CSS, "".join(parts)))


def export_design(res, base_dir, write_json=True):
    """Записва report.md, report.html, BOM.csv и design.json."""
    folder = os.path.join(base_dir, slugify(res["inputs"]["name"]))
    os.makedirs(folder, exist_ok=True)
    paths = {}

    def write(name, content, encoding="utf-8"):
        path = os.path.join(folder, name)
        with open(path, "w", encoding=encoding, newline="") as f:
            f.write(content)
        paths[name] = path
        return path

    write("report.md", build_report_markdown(res))
    write("report.html", build_report_html(res))
    write("BOM.csv", build_bom_csv(res), encoding="utf-8-sig")
    if write_json:
        write("design.json", json.dumps(res, ensure_ascii=False, indent=2))
    paths["folder"] = folder
    return paths





