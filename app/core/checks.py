"""Engineering checks for computed aircraft designs."""

import math

from . import aero
from . import layout
from . import presets
from . import printcost
from . import structmat


def _check(level, title, detail):
    """Един ред в списъка с проверки."""
    return {"level": level, "title": title, "detail": detail}


def build_checks(cfg, geom, stall, spec, cg_res, st, summary, total_g,
                 airframe_g, payload_g, wing_loading, re_cruise, converged,
                 fus, tail, feasible=True):
    """Build explanatory warnings and checks for the computed design."""
    mission = cfg["mission"]
    checks = []
    total_kg = total_g / 1000.0

    # 1. Конвергенция на масовия бюджет
    if converged and feasible:
        checks.append(_check("ok", "Масовият бюджет е стабилен",
                             "Итерациите се събраха: конструкцията и "
                             "оборудването са в равновесие."))
    elif converged:
        checks.append(_check("info", "Масовият бюджет има решение",
                             "Равновесието съществува, но дизайнът е "
                             "недопустим по друга проверка (виж грешките)."))
    else:
        checks.append(_check("error", "Няма решение на масовия бюджет",
                             "Конструкцията расте по-бързо от подемната "
                             "сила — решение не съществува. Това НЕ е "
                             "изчерпан лимит на итерациите."))

    # 1б. Възможно ли е изобщо това тегло при този филамент
    wl_req = cfg.get("wing_loading_requested", cfg["wing_loading"])
    wl_use = cfg.get("wing_loading_used", wl_req)
    if not feasible:
        if converged:
            detail = ("При %.0f g/dm² и „%s“ конструкцията заема над 60%% "
                      "от общата маса — масовият бюджет има решение, но "
                      "то е недопустимо. Смени на LW-PLA, намали "
                      "периметрите или намали натоварването на крилото."
                      % (wl_req, cfg["filament"]["name"]))
        else:
            detail = ("При %.0f g/dm² и „%s“ печатната конструкция расте "
                      "по-бързо от подемната сила — решение не съществува "
                      "(пробвано до %.0f g/dm²). Смени на LW-PLA, намали "
                      "периметрите или намали натоварването на крилото."
                      % (wl_req, cfg["filament"]["name"], wl_use))
        checks.append(_check("error",
                             "Конструкцията не може да носи себе си",
                             detail))
    if abs(wl_use - wl_req) > 0.5:
        checks.append(_check(
            "warn", "Натоварването на крилото е променено",
            "При %.0f g/dm² конструкцията не се носи; целеви са %.0f g/dm², "
            "а реалното натоварване е %.1f g/dm²."
            % (wl_req, wl_use, wing_loading)))

    # 2. Натоварване на крилото
    lo, hi = mission["wing_loading_range"]
    if payload_g <= 0:
        checks.append(_check("warn", "Няма зададен товар",
                             "Общото тегло е 0 g — моделът е изчислен само "
                             "от конструкцията. Задай масата на оборудването."))
    if lo <= wing_loading <= hi:
        checks.append(_check("ok", "Натоварване на крилото",
                             "%.1f g/dm² — в диапазона %.0f–%.0f g/dm² за "
                             "„%s“." % (wing_loading, lo, hi,
                                        mission["label"])))
    elif wing_loading < lo:
        checks.append(_check("warn", "Много ниско натоварване на крилото",
                             "%.1f g/dm² (под %.0f). Моделът ще е бавен и "
                             "чувствителен на вятър." % (wing_loading, lo)))
    else:
        checks.append(_check("warn", "Високо натоварване на крилото",
                             "%.1f g/dm² (над %.0f). По-висока скорост на "
                             "кацане и по-малко резерв." % (wing_loading, hi)))

    # 3. Скорост на загуба на подемна сила
    v_stall = stall["v_stall_ms"]
    if mission.get("hand_launch") and v_stall > 9.5:
        checks.append(_check("warn", "Трудно хвърляне от ръка",
                             "V_stall = %.1f m/s. За хвърляне от ръка е добре "
                             "под 8–9 m/s — увеличи площта или намали теглото."
                             % v_stall))
    else:
        checks.append(_check("ok", "Скорост на загуба на подемна сила",
                             "V_stall = %.1f m/s (%.0f km/h)."
                             % (v_stall, v_stall * 3.6)))

    # 4. Число на Рейнолдс
    if re_cruise < 60000:
        checks.append(_check("warn", "Много ниско число на Рейнолдс",
                             "Re = %.0f. Под 60 000 профилът губи подемна "
                             "сила — мини на по-дебел профил и по-голям хорд."
                             % re_cruise))
    elif re_cruise < 100000:
        checks.append(_check("warn", "Ниско число на Рейнолдс",
                             "Re = %.0f. CL_max е намален с ~%.0f%%; моделът "
                             "ще лети, но с по-ниско L/D."
                             % (re_cruise,
                                (1 - stall["cl_max"] / stall["cl_max_catalog"])
                                * 100.0)))
    else:
        checks.append(_check("ok", "Число на Рейнолдс",
                             "Re = %.0f — профилът работи в добрия си режим."
                             % re_cruise))

    re_lo, re_hi = cfg["airfoil"].get("re_range", (0.0, 0.0))
    if re_lo and re_cruise < re_lo * 0.8:
        checks.append(_check(
            "warn", "Re под диапазона на профила",
            "Re = %.0f, а %s работи добре от ~%.0f. Избери по-дебел профил "
            "или по-голям хорд."
            % (re_cruise, cfg["airfoil"]["name"], re_lo)))
    elif re_hi and re_cruise > re_hi * 1.2:
        checks.append(_check(
            "warn", "Re над диапазона на профила",
            "Re = %.0f, а %s е предвиден до ~%.0f."
            % (re_cruise, cfg["airfoil"]["name"], re_hi)))

    # 5. Тяга — сравнява се с тягата при ПРЕПОРЪЧАНАТА мощност (иначе
    # проверката е тавтологична: мощността се вдига точно до целта).
    tw_t = spec["thrust_to_weight_target"]
    tw_a = spec["thrust_to_weight_actual"]
    tw_rec = spec.get("thrust_to_weight_at_recommended", tw_a)
    if tw_rec < 0.9 * tw_t:
        checks.append(_check(
            "warn", "Тягата изисква повече мощност от препоръчаната",
            "При препоръчаните %.0f W/kg тягата е %.2f : 1 (цел %.2f : 1); "
            "мощността е вдигната до %.0f W (%.0f W/kg). Провери дали "
            "моторът/ESC издържат, или сложи по-голямо витло (%d\" сега)."
            % (spec["power_to_weight"], tw_rec, tw_t,
               spec["p_max_elec_w"],
               spec["p_max_elec_w"] / total_kg if total_kg > 0 else 0.0,
               spec["prop_d_in"])))
    else:
        checks.append(_check("ok", "Тяга",
                             "%.2f : 1 (цел %.2f : 1) при %d W и витло "
                             "%d инча." % (tw_a, tw_t,
                                           round(spec["p_max_elec_w"]),
                                           spec["prop_d_in"])))

    # 6. Мощност
    p2w_act = spec["p_max_elec_w"] / total_kg if total_kg > 0 else 0.0
    if p2w_act > 1.6 * spec["power_to_weight"]:
        checks.append(_check("warn", "Много висока мощност за типа",
                             "%.0f W/kg при препоръчани %.0f W/kg — тежък "
                             "мотор/батерия и къс полет."
                             % (p2w_act, spec["power_to_weight"])))
    else:
        checks.append(_check("ok", "Мощност",
                             "%.0f W/kg, макс. ток %.1f A (ESC %d A)."
                             % (p2w_act, spec["i_max_a"], spec["esc_a"])))

    # 7. Витло спрямо размаха и мощността
    prop_mm = spec["prop_d_in"] * 25.4
    if prop_mm > 0.32 * geom["span_mm"]:
        checks.append(_check("warn", "Голямо витло за размаха",
                             "%d инча (%.0f mm) при размах %.0f mm — провери "
                             "клиренса и реактивния момент."
                             % (spec["prop_d_in"], prop_mm, geom["span_mm"])))
    if spec.get("rpm_conflict"):
        reasons = []
        if spec.get("rpm_pitch_over_tip"):
            reasons.append("стъпката иска %.0f об/мин, над лимита %.0f"
                           % (spec["rpm_min"], spec["rpm_tip"]))
        if spec.get("rpm_power_over_tip"):
            reasons.append("мощността иска %.0f об/мин, над лимита %.0f"
                           % (spec["rpm_power"], spec["rpm_tip"]))
        if spec.get("rpm_power_below_pitch"):
            reasons.append("при тази мощност витлото достига %.0f об/мин, "
                           "а за крейсерската стъпка са нужни %.0f"
                           % (spec["rpm_power"], spec["rpm_min"]))
        if spec.get("rpm_capped"):
            reasons.append("оборотите са ограничени до %.0f, за да не се "
                           "надхвърли върховата скорост при пълна батерия"
                           % spec["rpm_target"])
        checks.append(_check(
            "warn", "Витлото не е съгласувано с мощността",
            "%d×%d инча: %s. Сложи витло с по-малка стъпка/диаметър или "
            "промени мощността и клетките."
            % (spec["prop_d_in"], spec["prop_pitch_in"],
               "; ".join(reasons) or "оборотите са извън разумния режим")))
    else:
        checks.append(_check("info", "Витло",
                             "%d×%d инча, ~%.0f об/мин (J ≈ %.2f), Kv ≈ %.0f."
                             % (spec["prop_d_in"], spec["prop_pitch_in"],
                                spec["rpm_target"],
                                spec.get("advance_ratio_cruise", 0.0),
                                spec["kv"])))

    # 8. Батерия — ток и време
    c_needed = spec["battery"]["c_rating_needed"]
    if c_needed > 50:
        checks.append(_check("error", "Батерията е претоварена",
                             "Нужни са %.0fC — над 50C е рисковано. Вземи "
                             "по-голям капацитет или по-нисък Kv." % c_needed))
    elif c_needed > 35:
        checks.append(_check("warn", "Висок ток от батерията",
                             "Нужни са %.0fC. Вземи пакет с поне %.0fC."
                             % (c_needed, c_needed + 10)))
    else:
        checks.append(_check("ok", "Батерия — ток",
                             "Нужни са %.0fC; стандартен 30–45C пакет е "
                             "достатъчен." % c_needed))

    if spec.get("esc_saturated"):
        checks.append(_check(
            "error", "ESC над стандартния размер",
            "Нужни са %.0f A (1.25×%.1f A), а най-големият стандартен ESC "
            "е %d A. Раздели задвижването, вдигни клетките или намали "
            "мощността."
            % (spec["esc_required_a"], spec["i_max_a"],
               presets.ESC_SIZES_A[-1])))

    end_act = spec["battery"]["endurance_min"]
    end_tgt = spec["battery"]["endurance_target_min"]
    if end_act < 0.8 * end_tgt:
        checks.append(_check("warn", "По-малко време от желаното",
                             "%.0f мин при цел %.0f мин — батерията е "
                             "ограничена от теглото." % (end_act, end_tgt)))
    elif end_act > 1.5 * end_tgt:
        cap_for_target = (spec["battery"]["capacity_mah"] * end_tgt / end_act
                          if end_act > 0 else spec["battery"]["capacity_mah"])
        checks.append(_check(
            "info", "По-голяма батерия от нужното",
            "%.0f мин при цел %.0f мин — за целта стигат ~%.0f mAh "
            "(~%.0f g по-малко тегло)." % (
                end_act, end_tgt, cap_for_target,
                max(0.0, spec["battery"]["mass_g"]
                    - spec["battery"]["energy_wh"] * end_tgt / end_act
                    / presets.BATTERY_SPECIFIC_ENERGY_WH_KG * 1000.0))))
    else:
        checks.append(_check("ok", "Време на полет",
                             "~%.0f мин в крейсер (%d mAh, %dS)."
                             % (end_act,
                                round(spec["battery"]["capacity_mah"]),
                                spec["cells"])))

    # 9. Център на тежестта
    sm = cg_res["static_margin_actual"]
    if sm < 0.02:
        checks.append(_check("error", "Опасен център на тежестта",
                             "ЦТ е на %.1f%% MAC — зад неутралната точка. "
                             "Моделът ще е нестабилен; премести маса напред."
                             % cg_res["cg_pct_mac"]))
    elif sm < 0.05:
        checks.append(_check("warn", "Малък статичен запас",
                             "%.0f%% MAC — допустимо за 3D, но не за треньор."
                             % (sm * 100.0)))
    elif sm <= 0.16:
        checks.append(_check("ok", "Статичен запас",
                             "%.0f%% MAC (цел %.0f%%), ЦТ на %.1f%% MAC "
                             "(неутрална точка %.0f mm)."
                             % (sm * 100.0,
                                cg_res["static_margin_target"] * 100.0,
                                cg_res["cg_pct_mac"],
                                cg_res.get("x_np_mm", 0.0))))
    else:
        checks.append(_check("warn", "Голям статичен запас",
                             "%.0f%% MAC — носът е тежък, моделът ще иска "
                             "много тример." % (sm * 100.0)))

    if cg_res.get("battery_x_required_mm") is not None \
            and not cg_res.get("cg_achievable", True):
        checks.append(_check(
            "error", "Целевият ЦТ не е постижим",
            "Реалният ЦТ е %.0f mm (%.1f%% MAC) — статичният запас е %.0f%% "
            "вместо целевите %.0f%%. Числата в отчета са за РЕАЛНИЯ ЦТ, не "
            "за целевия."
            % (cg_res["x_cg_mm"], cg_res["cg_pct_mac"],
               cg_res["static_margin_actual"] * 100.0,
               cg_res["static_margin_target"] * 100.0)))

    shift = cg_res["battery_shift_mm"]
    x_bat = cg_res.get("battery_x_required_mm")
    x_placed = cg_res.get("battery_x_placed_mm", x_bat)
    prop_layout = cfg.get("propulsion_layout", "tractor")
    if prop_layout == "pusher":
        checks.append(_check(
            "info", "Бутащо витло",
            "Моторът е в опашката: потокът към крилото е чист, но опашката "
            "е по-тежка. Провери просвета на витлото (Ø %.0f mm) спрямо "
            "кила и земята." % prop_mm))
        if x_bat is not None and fus.get("length_mm", 0) > 0 \
                and x_bat < 0.10 * fus["length_mm"]:
            checks.append(_check(
                "warn", "Къс нос за бутащо витло",
                "За баланс батерията трябва да е на %.0f mm (под 10%% от "
                "дължината). Удължи носа или премести крилото напред."
                % x_bat))
    elif prop_layout == "twin":
        motors = int(cfg.get("motor_count", 2))
        checks.append(_check(
            "info", "Два мотора",
            "%d мотора по %.0f W; ESC %d A на мотор, витла Ø %.0f mm."
            % (motors, spec.get("p_motor_elec_w", 0.0),
               spec.get("esc_a", 0), prop_mm)))
        y_motor = 0.35 * float(geom["span_mm"]) / 2.0
        clearance = y_motor - prop_mm / 2.0 - fus.get("width_mm", 0.0) / 2.0
        if clearance < 25.0:
            checks.append(_check(
                "warn", "Витлата са близо до тялото",
                "Остават %.0f mm между диска и стената на тялото (под "
                "25 mm). Премести моторите навън или вземи по-малки витла."
                % clearance))
    if cfg.get("tail_type") == "t_tail":
        checks.append(_check(
            "info", "T-опашка",
            "Стабилизаторът е на върха на кила — по-чист поток при бутащо "
            "витло, но килът носи цялата му сила. Провери якостта на кила "
            "и връзката към фюзелажа."))
    elif cfg.get("tail_type") == "v_tail":
        panel = layout.v_tail_panel(tail.get("s_h_m2", 0.0),
                                    tail.get("s_v_m2", 0.0),
                                    cfg.get("v_tail_deg", 35.0))
        checks.append(_check(
            "info", "V-опашка",
            "Ъгъл %.0f°: панел %.1f dm² (общо), проекции %.1f / %.1f dm². "
            "Ограничаваща е %s проекцията."
            % (panel["gamma_deg"], panel["s_panel_m2"] * 100.0,
               panel["s_h_eff_m2"] * 100.0, panel["s_v_eff_m2"] * 100.0,
               panel["limited_by"])))
    if x_bat is None:
        checks.append(_check("warn", "Няма батерия в списъка",
                             "Добави батерия, за да може ЦТ да се балансира."))
    elif not cg_res["battery_feasible"]:
        if x_bat < 0:
            checks.append(_check(
                "error", "Моделът излиза тежък на опашка",
                "Дори батерия в самото начало на носа не стига за целта "
                "(нужни са %.0f mm пред носа). Конструкцията отзад е твърде "
                "тежка — намали масата на опашката (LW-PLA, по-малко "
                "периметри) или премести сервата напред." % abs(x_bat)))
        else:
            checks.append(_check(
                "error", "Батерията не може да балансира модела",
                "Тя трябва да е на %.0f mm от носа — извън фюзелажа "
                "(дължина %.0f mm). Преместена е на %.0f mm; ЦТ е %.1f%% MAC."
                % (x_bat, fus["length_mm"], x_placed,
                   cg_res["cg_pct_mac"])))
    elif abs(shift) <= 25:
        checks.append(_check("ok", "Баланс с батерията",
                             "Батерията на ~%.0f mm от носа е на добро място."
                             % x_placed))
    elif abs(shift) <= 60:
        checks.append(_check("warn", "Ще трябва разместване",
                             "Постави батерията на %.0f mm от носа "
                             "(по подразбиране %.0f mm)."
                             % (x_placed, cg_res["battery_x_default_mm"])))
    else:
        checks.append(_check("warn", "Голямо разместване на батерията",
                             "Постави батерията на %.0f mm от носа "
                             "(по подразбиране %.0f mm, отместване %.0f mm)."
                             % (x_placed, cg_res["battery_x_default_mm"],
                                abs(shift))))

    # 10. Маса на конструкцията
    air_pct = 100.0 * airframe_g / total_g if total_g > 0 else 0.0
    if air_pct > 60.0:
        checks.append(_check("error", "Прекалено тежка конструкция",
                             "%.0f%% от масата е печат. Смени на LW-PLA и "
                             "1 периметър." % air_pct))
    elif air_pct > 45.0:
        checks.append(_check("warn", "Тежка конструкция",
                             "%.0f%% от масата е печат (нормално 30–40%%). "
                             "LW-PLA или по-малко периметри ще помогнат."
                             % air_pct))
    else:
        checks.append(_check("ok", "Маса на конструкцията",
                             "%.0f g печат (%.0f%% от общата маса)."
                             % (airframe_g, air_pct)))

    # 11. Якост на спаровете
    if not st["print_ok"]:
        checks.append(_check("warn", "Печатан спар не е достатъчен",
                             "Нужни са %.1f mm² капси, печатани — %.1f mm². "
                             "Добави карбонова лента %.0f×%.1f mm × %d на "
                             "всеки капс."
                             % (st["cap_area_req_mm2"],
                                st["cap_area_print_mm2"],
                                st["carbon"]["width_mm"],
                                st["carbon"]["thickness_mm"],
                                st["carbon"]["count"])))
    elif st.get("carbon_for_stiffness"):
        checks.append(_check(
            "warn", "Нужен е карбон за коравина",
            "Якостта стига (%.1f mm² от %.1f mm²), но само печатаният капс "
            "се огъва %.0f mm при лимит %.0f mm. С включения карбон "
            "%.0f×%.1f mm × %d деформацията е %.1f mm."
            % (st["cap_area_req_mm2"], st["cap_area_print_mm2"],
               st["deflection_print_mm"], st["deflection_limit_mm"],
               st["carbon"]["width_mm"], st["carbon"]["thickness_mm"],
               st["carbon"]["count"], st["deflection_carbon_mm"])))
    else:
        checks.append(_check("ok", "Спарове",
                             "Печатани капси: %.1f mm² при нужни %.1f mm² "
                             "(височина на пояса %.1f mm, M_корен %.1f N·m)."
                             % (st["cap_area_print_mm2"],
                                st["cap_area_req_mm2"],
                                st["spar_height_mm"], st["m_root_nm"])))

    joiner = st.get("joiner_tube") or {}
    if joiner.get("material", "carbon") != "carbon":
        jname = structmat.get(joiner["material"])["name"]
        if not joiner.get("od_mm"):
            checks.append(_check("error", "Джойнер: няма профил в каталога",
                                 "%s не издържа при огъващия момент от %.1f "
                                 "N·m в нито един профил. Смени материала "
                                 "или намали масата." % (jname, st["m_ult_nm"])))
        elif joiner.get("stress_mpa") is not None and \
                joiner["stress_mpa"] > joiner["allow_mpa"]:
            checks.append(_check("error", "Джойнер (%s): трайно огъване"
                                 % jname,
                                 "%.0f MPa при допустимо %.0f MPa."
                                 % (joiner["stress_mpa"], joiner["allow_mpa"])))
        else:
            checks.append(_check("ok", "Джойнер (%s)" % jname,
                                 "Ø%.0f/%.0f mm, %.0f MPa при допустимо %.0f MPa."
                                 % (joiner["od_mm"], joiner["id_mm"],
                                    joiner["stress_mpa"], joiner["allow_mpa"])))
    if not st.get("adhesive_ok", True):
        checks.append(_check("error", "Лепилна връзка на джойнера",
                             "Срязване %.1f MPa при допустимо %.1f MPa за "
                             "лепилото. Увеличи дължината на джойнера или "
                             "избери по-дебел профил."
                             % (st["adhesive_shear_mpa"],
                                structmat.ADHESIVE_SHEAR_ALLOW_MPA)))
    else:
        checks.append(_check("ok", "Лепилна връзка на джойнера",
                             "Срязване %.2f MPa при допустимо %.0f MPa "
                             "(епоксид, ориентировъчно)."
                             % (st["adhesive_shear_mpa"],
                                structmat.ADHESIVE_SHEAR_ALLOW_MPA)))

    if not st.get("compression_ok", True):
        checks.append(_check("error", "Печатаният капс не издържа на натиск",
                             "Напрежение %.1f MPa при допустимо %.1f MPa. "
                             "Увеличи ширината на капса или добави карбон."
                             % (st["cap_compression_mpa"],
                                st["compression_allow_mpa"])))
    if not st.get("buckling_ok", True):
        checks.append(_check("warn", "Локално изкълчване на капса",
                             "Напрежение %.1f MPa при критично %.1f MPa. "
                             "Увеличи дебелината на стената или добави "
                             "карбон." % (st["cap_compression_mpa"],
                                          st["buckling_stress_mpa"])))

    if not st["wall_ok"]:
        checks.append(_check("error", "Прекалено тънка стена",
                             "%.2f mm при минимум %.2f mm за тази дюза."
                             % (st["wall_mm"], st["min_wall_mm"])))
    if not st["deflection_ok"]:
        defl = (st["deflection_carbon_mm"] if st["carbon_required"]
                else st["deflection_print_mm"])
        checks.append(_check("error", "Голяма деформация на крилото",
                             "%.0f mm при лимит %.0f mm. Увеличи височината "
                             "на спаровия пояс или добави карбон."
                             % (defl, st["deflection_limit_mm"])))

    # 12. Печат
    for problem in printcost.fit_problems(geom, tail, fus, cfg):
        checks.append(_check("error", "Печат: частта не се побира", problem))
    plan = printcost.split_plan(geom, tail, cfg)
    if plan["wing_chord_pieces"] > 1 or plan["tail_chord_pieces"] > 1 \
            or plan["tail_height_pieces"] > 1:
        checks.append(_check(
            "info", "Части с разрез за леглото",
            "Крилото: %d по размаха × %d по хорда; опашката: %d по хорда × "
            "%d по височина. Съединява се с джойнер и лепило (проверката на "
            "лепилната връзка е във Фаза 2)."
            % (plan["wing_span_pieces"], plan["wing_chord_pieces"],
               plan["tail_chord_pieces"], plan["tail_height_pieces"])))
    if cfg.get("infill", 0) > 40:
        checks.append(_check(
            "warn", "Висок infill",
            "Моделът за печат е калибриран за тънкостенни крила (0–25% "
            "infill). При %d%% масата/времето може да са подценени."
            % round(cfg["infill"])))
    total_h = summary["time_h"]
    if total_h > 40:
        checks.append(_check("warn", "Дълъг печат",
                             "~%.0f часа общо в %d части."
                             % (total_h, summary["pieces"])))
    else:
        checks.append(_check("ok", "Печат",
                             "~%.1f часа, %.0f g филамент, %d части."
                             % (total_h, summary["total_mass_g"],
                                summary["pieces"])))

    if not fus.get("battery_fits", True):
        checks.append(_check("warn", "Батерията не влиза в носа",
                             "Кутията за батерия е %.0f×%.0f×%.0f mm — "
                             "фюзелажът е къс."
                             % (fus["battery_box_mm"][0],
                                fus["battery_box_mm"][1],
                                fus["battery_box_mm"][2])))
    else:
        checks.append(_check("info", "Фюзелаж",
                             "%.0f × %.0f × %.0f mm (Д×Ш×В), място за "
                             "батерия %.0f×%.0f×%.0f mm."
                             % (fus["length_mm"], fus["width_mm"],
                                fus["height_mm"],
                                fus["battery_box_mm"][0],
                                fus["battery_box_mm"][1],
                                fus["battery_box_mm"][2])))

    # 13. Профил: крило без опашка / опашка
    if not cfg["has_tail"] and cfg["airfoil"]["kind"] != "reflexed":
        checks.append(_check("warn", "Профил за крило без опашка",
                             "Избраният профил не е reflexed — за flying "
                             "wing избери MH 45, иначе ще трябва тример."))
    elif cfg["has_tail"] and cfg["airfoil"]["kind"] == "reflexed":
        checks.append(_check("warn", "Reflex профил с опашка",
                             "MH 45 е за крило без опашка; за модел с "
                             "опашка избери NACA 2412 или Clark Y."))

    # 14. Обемни коефициенти на опашката
    if cfg["has_tail"]:
        s_h_ratio = (100.0 * tail["s_h_m2"] / geom["area_m2"]
                     if geom["area_m2"] > 0 else 0.0)
        if 0.35 <= cfg["vh"] <= 0.80:
            if tail.get("tail_fit_limited"):
                checks.append(_check(
                    "ok", "Хоризонтална опашка",
                    "S_h = %.0f cm² (%.0f%% от крилото), V_h = %.2f, рамо "
                    "%.0f mm (конфиг. %.0f — ограничено от фюзелажа)."
                    % (tail["s_h_dm2"] * 100.0, s_h_ratio, cfg["vh"],
                       tail["l_h_mm"], tail.get("l_h_configured_mm",
                                                tail["l_h_mm"]))))
            else:
                checks.append(_check("ok", "Хоризонтална опашка",
                                     "S_h = %.0f cm² (%.0f%% от крилото), "
                                     "V_h = %.2f, рамо %.0f mm."
                                     % (tail["s_h_dm2"] * 100.0, s_h_ratio,
                                        cfg["vh"], tail["l_h_mm"])))
        else:
            checks.append(_check("warn", "Нестандартен V_h",
                                 "V_h = %.2f (нормално 0.35–0.80)."
                                 % cfg["vh"]))
        if 0.015 <= cfg["vv"] <= 0.060:
            checks.append(_check("ok", "Вертикална опашка",
                                 "S_v = %.0f cm², V_v = %.3f е в нормата "
                                 "(0.015–0.060)."
                                 % (tail["s_v_dm2"] * 100.0, cfg["vv"])))
        else:
            checks.append(_check("warn", "Нестандартен V_v",
                                 "V_v = %.3f (нормално 0.015–0.060)."
                                 % cfg["vv"]))
        if tail.get("tail_fit_limited"):
            checks.append(_check(
                "info", "Опашката е ограничена от фюзелажа",
                "Конфигурираното рамо %.0f mm не се побира; използвано е "
                "%.0f mm. S_h/S_v са увеличени до %.1f/%.1f dm², за да "
                "запазят V_h/V_v. Ако това не е желано, удължи фюзелажа или "
                "намали tail_arm_ratio."
                % (tail.get("l_h_configured_mm", tail["l_h_mm"]),
                   tail["l_h_mm"], tail["s_h_dm2"], tail["s_v_dm2"])))
    else:
        checks.append(_check("info", "Крило без опашка",
                             "Elevoni управляват наклон и тангаж; "
                             "статичният запас трябва да е 3–7%% MAC."))

    return checks
