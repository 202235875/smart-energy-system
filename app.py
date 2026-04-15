import streamlit as st
import requests
import pandas as pd
import altair as alt

st.set_page_config(page_title="스마트 에너지 관리 시스템", layout="wide")

st.title("스마트 에너지 관리 시스템")
st.caption("실제 날씨를 기반으로 태양광 발전량, 건물 소비량, 배터리 운용을 분석합니다.")

# -----------------------------
# 사이드바 입력
# -----------------------------
st.sidebar.header("분석 설정")

city = st.sidebar.text_input("단일 도시 분석", value="Seongnam-si")
compare_cities = st.sidebar.text_input(
    "비교할 도시들 (쉼표로 구분)",
    value="Seongnam-si, Seoul, Tokyo, Dubai"
)

st.sidebar.subheader("태양광 설정")
panel_capacity = st.sidebar.number_input("태양광 설비 용량 (kW)", min_value=1.0, value=5.0, step=1.0)
panel_efficiency = st.sidebar.slider("태양광 효율", min_value=0.1, max_value=0.3, value=0.2, step=0.01)
system_loss = st.sidebar.slider("시스템 손실 (%)", min_value=0, max_value=30, value=15, step=1)

panel_tilt = st.sidebar.slider("패널 경사각 (도)", min_value=0, max_value=60, value=30, step=1)
panel_azimuth = st.sidebar.selectbox("패널 방향", ["남향", "동향", "서향", "평지붕/무방향"])

st.sidebar.subheader("배터리 설정")
battery_capacity = st.sidebar.number_input("배터리 용량 (kWh)", min_value=1.0, value=10.0, step=1.0)
battery_percent = st.sidebar.slider("현재 배터리 잔량 (%)", min_value=0, max_value=100, value=50)

st.sidebar.subheader("건물 설정")
building_day_usage = st.sidebar.number_input("낮 시간 건물 소비량 (kWh)", min_value=0.1, value=1.5, step=0.1)
building_night_usage = st.sidebar.number_input("밤 시간 건물 소비량 (kWh)", min_value=0.1, value=0.5, step=0.1)
building_type = st.sidebar.selectbox("건물 유형 선택", ["학교", "오피스", "아파트", "상가"])

run_analysis = st.sidebar.button("분석 시작")


def building_usage(building_type, hour, temperature, day_usage, night_usage):
    if building_type == "학교":
        if 8 <= hour <= 17:
            base_usage = day_usage + 0.3
        else:
            base_usage = night_usage

    elif building_type == "오피스":
        if 9 <= hour <= 18:
            base_usage = day_usage + 0.5
        else:
            base_usage = night_usage

    elif building_type == "아파트":
        if 6 <= hour <= 9 or 18 <= hour <= 23:
            base_usage = day_usage + 0.4
        else:
            base_usage = night_usage + 0.2

    elif building_type == "상가":
        if 10 <= hour <= 21:
            base_usage = day_usage + 0.6
        else:
            base_usage = night_usage

    else:
        base_usage = day_usage if 9 <= hour <= 18 else night_usage

    if temperature >= 28:
        base_usage += 1.0
    elif temperature <= 5:
        base_usage += 0.8

    return base_usage


def find_city(city_name):
    geo_url = "https://geocoding-api.open-meteo.com/v1/search"
    geo_params = {
        "name": city_name,
        "count": 10,
        "language": "en",
        "format": "json"
    }

    geo_response = requests.get(geo_url, params=geo_params, timeout=20)
    geo_response.raise_for_status()
    geo_data = geo_response.json()

    if "results" not in geo_data or len(geo_data["results"]) == 0:
        return None

    results = geo_data["results"]

    selected = None
    for r in results:
        if r.get("country") == "South Korea":
            selected = r
            break

    if selected is None:
        selected = results[0]

    return selected


def tilt_factor_func(tilt_deg):
    """
    경사각 보정:
    30도를 최적값으로 가정하고,
    너무 평평하거나 너무 가파르면 소폭 감점
    """
    diff = abs(tilt_deg - 30)
    factor = 1.0 - (diff * 0.005)
    return max(0.85, min(1.0, factor))


def azimuth_factor_func(azimuth, hour):
    """
    방향 보정:
    - 남향: 하루 전체 평균적으로 가장 유리
    - 동향: 오전 유리, 오후 불리
    - 서향: 오후 유리, 오전 불리
    - 평지붕/무방향: 무난한 중간값
    """
    if azimuth == "남향":
        return 1.0

    if azimuth == "동향":
        if 6 <= hour <= 11:
            return 1.0
        elif 12 <= hour <= 15:
            return 0.92
        else:
            return 0.85

    if azimuth == "서향":
        if 6 <= hour <= 11:
            return 0.85
        elif 12 <= hour <= 15:
            return 0.95
        else:
            return 1.0

    # 평지붕/무방향
    return 0.93


def make_recommendations(summary, today_df):
    recommendations = []

    self_sufficiency = summary["자급률(%)"]
    grid_ratio = summary["외부전력 비율(%)"]
    total_grid = today_df["grid"].sum()
    avg_cloud = summary["평균 구름량(%)"]
    avg_temp = summary["평균 기온(°C)"]
    max_battery = today_df["battery_level"].max()
    min_battery = today_df["battery_level"].min()

    if self_sufficiency < 40:
        recommendations.append("태양광 용량이 현재 소비량 대비 부족한 편입니다. 태양광 설비 용량을 늘리는 것을 고려해보세요.")
    elif self_sufficiency < 70:
        recommendations.append("일부 자급은 가능하지만 외부 전력 의존이 남아 있습니다. 태양광 또는 배터리 용량을 조금 더 키우면 개선될 수 있습니다.")
    else:
        recommendations.append("현재 조건에서 자급률이 높은 편입니다. 비교적 안정적인 에너지 운영이 가능합니다.")

    if grid_ratio > 50:
        recommendations.append("외부전력 비율이 높습니다. 건물 소비량 조정이나 태양광 용량 확장이 필요할 수 있습니다.")
    elif grid_ratio > 20:
        recommendations.append("외부전력 사용이 일부 발생합니다. 피크 시간대 소비를 줄이면 개선될 수 있습니다.")

    if max_battery >= battery_capacity * 0.95 and self_sufficiency > 70:
        recommendations.append("배터리가 자주 가득 차는 것으로 보입니다. 배터리 용량을 더 키우기보다는 남는 전력 활용 방안을 고민하는 것이 좋습니다.")

    if min_battery <= battery_capacity * 0.1 and total_grid > 0:
        recommendations.append("배터리 잔량이 자주 낮아집니다. 배터리 용량을 늘리면 외부 전력 사용을 줄일 가능성이 있습니다.")

    if avg_cloud >= 70:
        recommendations.append("구름량이 높아 태양광 발전 여건이 좋지 않습니다. 이 지역은 날씨 영향이 큰 편입니다.")
    elif avg_cloud < 30:
        recommendations.append("구름량이 낮아 태양광 발전 여건이 좋은 편입니다.")

    if avg_temp >= 28:
        recommendations.append("기온이 높아 냉방 수요가 증가했을 가능성이 큽니다. 여름철에는 소비량 관리가 중요합니다.")
    elif avg_temp <= 5:
        recommendations.append("기온이 낮아 난방 수요가 증가했을 가능성이 큽니다. 겨울철에는 소비량이 커질 수 있습니다.")

    if building_type == "아파트":
        recommendations.append("아파트는 아침과 저녁 시간대 사용량이 커지는 패턴으로 반영되었습니다.")
    elif building_type == "오피스":
        recommendations.append("오피스는 업무시간 중심의 전력 소비 패턴으로 반영되었습니다.")
    elif building_type == "학교":
        recommendations.append("학교는 주간 활동 중심의 소비 패턴으로 반영되었습니다.")
    elif building_type == "상가":
        recommendations.append("상가는 낮부터 저녁까지 전력 사용이 큰 패턴으로 반영되었습니다.")

    if system_loss >= 20:
        recommendations.append("시스템 손실이 큰 설정입니다. 인버터 효율이나 배선 손실을 점검하면 발전 효율 개선에 도움이 될 수 있습니다.")

    if panel_azimuth != "남향":
        recommendations.append(f"현재 패널 방향은 {panel_azimuth}입니다. 일반적으로 남향이 가장 유리한 편입니다.")

    if panel_tilt < 15 or panel_tilt > 45:
        recommendations.append("현재 경사각은 일반적인 최적 범위에서 다소 벗어나 있습니다. 25~35도 부근이 더 유리할 수 있습니다.")

    return recommendations


def run_city_analysis(city_name):
    selected = find_city(city_name)
    if selected is None:
        return None, f"{city_name} 도시를 찾지 못했습니다."

    lat = selected["latitude"]
    lon = selected["longitude"]

    weather_url = "https://api.open-meteo.com/v1/forecast"
    weather_params = {
        "latitude": lat,
        "longitude": lon,
        "hourly": "shortwave_radiation,temperature_2m,cloud_cover",
        "timezone": "Asia/Seoul"
    }

    weather_response = requests.get(weather_url, params=weather_params, timeout=20)
    weather_response.raise_for_status()
    weather_data = weather_response.json()

    df = pd.DataFrame({
        "time": weather_data["hourly"]["time"],
        "radiation": weather_data["hourly"]["shortwave_radiation"],
        "temperature": weather_data["hourly"]["temperature_2m"],
        "cloud_cover": weather_data["hourly"]["cloud_cover"]
    })

    df["time"] = pd.to_datetime(df["time"])
    today = df[df["time"].dt.date == df["time"].dt.date.iloc[0]].copy()

    # -----------------------------
    # 전문성 높인 태양광 모델
    # 1) 시스템 손실
    # 2) 온도 영향
    # 3) 패널 방향
    # 4) 경사각
    # -----------------------------
    loss_factor = (100 - system_loss) / 100
    temp_coefficient = -0.004
    temp_effect = 1 + temp_coefficient * (today["temperature"] - 25)
    temp_effect = temp_effect.clip(lower=0.7, upper=1.1)

    tilt_factor = tilt_factor_func(panel_tilt)
    today["tilt_factor"] = tilt_factor

    today["azimuth_factor"] = today["time"].dt.hour.apply(lambda h: azimuth_factor_func(panel_azimuth, h))

    today["power"] = (
        today["radiation"]
        * panel_capacity
        * panel_efficiency
        * loss_factor
        * temp_effect
        * today["tilt_factor"]
        * today["azimuth_factor"]
        / 1000
    )

    today["usage"] = today.apply(
        lambda row: building_usage(
            building_type,
            row["time"].hour,
            row["temperature"],
            building_day_usage,
            building_night_usage
        ),
        axis=1
    )

    today["net"] = today["power"] - today["usage"]

    battery_energy = battery_capacity * (battery_percent / 100.0)
    current_battery = battery_energy

    battery_level_list = []
    charge_list = []
    discharge_list = []
    grid_list = []

    for _, row in today.iterrows():
        net = row["net"]

        if net > 0:
            charge = min(net, battery_capacity - current_battery)
            current_battery += charge
            discharge = 0.0
            grid = 0.0
        else:
            need = abs(net)
            discharge = min(need, current_battery)
            current_battery -= discharge
            grid = max(0.0, need - discharge)
            charge = 0.0

        battery_level_list.append(current_battery)
        charge_list.append(charge)
        discharge_list.append(discharge)
        grid_list.append(grid)

    today["battery_level"] = battery_level_list
    today["charge"] = charge_list
    today["discharge"] = discharge_list
    today["grid"] = grid_list
    today["temp_effect"] = temp_effect
    today["loss_factor"] = loss_factor

    total_power = today["power"].sum()
    total_usage = today["usage"].sum()
    total_net = today["net"].sum()
    total_grid = today["grid"].sum()
    max_power = today["power"].max()

    if total_usage > 0:
        self_sufficiency = ((total_usage - total_grid) / total_usage) * 100
        grid_ratio = (total_grid / total_usage) * 100
    else:
        self_sufficiency = 0.0
        grid_ratio = 0.0

    avg_temp = today["temperature"].mean()
    avg_cloud = today["cloud_cover"].mean()
    max_radiation = today["radiation"].max()
    avg_temp_effect = today["temp_effect"].mean()
    avg_azimuth_factor = today["azimuth_factor"].mean()

    summary = {
        "입력 도시": city_name,
        "분석 도시": selected["name"],
        "국가": selected.get("country", ""),
        "총 발전량(kWh)": round(total_power, 2),
        "총 소비량(kWh)": round(total_usage, 2),
        "순에너지(kWh)": round(total_net, 2),
        "자급률(%)": round(self_sufficiency, 1),
        "외부전력 비율(%)": round(grid_ratio, 1),
        "평균 기온(°C)": round(avg_temp, 1),
        "평균 구름량(%)": round(avg_cloud, 1),
        "최대 태양복사량(W/m²)": round(max_radiation, 1),
        "최대 발전량(kWh)": round(max_power, 2),
        "시스템 손실(%)": system_loss,
        "평균 온도 보정계수": round(avg_temp_effect, 3),
        "경사각 보정계수": round(tilt_factor, 3),
        "평균 방향 보정계수": round(avg_azimuth_factor, 3),
        "패널 방향": panel_azimuth,
        "패널 경사각(도)": panel_tilt
    }

    recommendations = make_recommendations(summary, today)

    return {
        "selected": selected,
        "today": today,
        "summary": summary,
        "recommendations": recommendations
    }, None


if run_analysis:
    try:
        # -----------------------------
        # 단일 도시 분석
        # -----------------------------
        result, error = run_city_analysis(city)

        if error:
            st.error(error)
        else:
            selected = result["selected"]
            today = result["today"]
            summary = result["summary"]
            recommendations = result["recommendations"]

            st.success(f"{selected['name']}, {selected.get('country', '')} 위치 찾음!")

            st.subheader("주요 결과")
            col1, col2, col3 = st.columns(3)
            col1.metric("총 발전량", f"{summary['총 발전량(kWh)']:.2f} kWh")
            col2.metric("총 소비량", f"{summary['총 소비량(kWh)']:.2f} kWh")
            col3.metric("최대 발전량", f"{summary['최대 발전량(kWh)']:.2f} kWh")

            col4, col5, col6 = st.columns(3)
            col4.metric("순에너지", f"{summary['순에너지(kWh)']:.2f} kWh")
            col5.metric("자급률", f"{summary['자급률(%)']:.1f} %")
            col6.metric("외부전력 비율", f"{summary['외부전력 비율(%)']:.1f} %")

            st.subheader("기상 및 모델 요약")
            w1, w2, w3, w4 = st.columns(4)
            w1.metric("평균 기온", f"{summary['평균 기온(°C)']:.1f} °C")
            w2.metric("평균 구름량", f"{summary['평균 구름량(%)']:.1f} %")
            w3.metric("최대 태양복사량", f"{summary['최대 태양복사량(W/m²)']:.1f} W/m²")
            w4.metric("평균 온도 보정계수", f"{summary['평균 온도 보정계수']:.3f}")

            m1, m2, m3 = st.columns(3)
            m1.metric("시스템 손실", f"{summary['시스템 손실(%)']} %")
            m2.metric("경사각 보정계수", f"{summary['경사각 보정계수']:.3f}")
            m3.metric("평균 방향 보정계수", f"{summary['평균 방향 보정계수']:.3f}")

            st.write(f"현재 패널 방향: **{summary['패널 방향']}**, 경사각: **{summary['패널 경사각(도)']}°**")

            st.subheader("시간대별 태양광 발전량")
            st.line_chart(today.set_index("time")["power"])

            st.subheader("태양광 발전량 vs 건물 소비량")
            st.line_chart(today.set_index("time")[["power", "usage"]])

            st.subheader("배터리 충전 / 방전 / 외부 전력")
            st.line_chart(today.set_index("time")[["charge", "discharge", "grid"]])

            st.subheader("배터리 잔량 변화")
            st.line_chart(today.set_index("time")["battery_level"])

            st.subheader("최종 에너지 분석")
            if summary["외부전력 비율(%)"] == 0:
                st.success("완전 자급 가능: 외부 전력 없이 운영할 수 있습니다.")
            else:
                st.warning(f"외부 전력 필요: {today['grid'].sum():.2f} kWh")

            st.subheader("자동 추천")
            for rec in recommendations:
                st.write(f"• {rec}")

            st.subheader("상세 데이터")
            st.dataframe(
                today[[
                    "time", "temperature", "cloud_cover", "radiation",
                    "temp_effect", "tilt_factor", "azimuth_factor",
                    "power", "usage", "net", "charge", "discharge", "grid", "battery_level"
                ]],
                use_container_width=True
            )

        # -----------------------------
        # 도시 비교 분석
        # -----------------------------
        st.subheader("도시 비교 분석")

        city_list = [c.strip() for c in compare_cities.split(",") if c.strip()]
        compare_results = []

        for c in city_list:
            result_compare, error_compare = run_city_analysis(c)
            if result_compare:
                compare_results.append(result_compare["summary"])

        if compare_results:
            compare_df = pd.DataFrame(compare_results)

            st.write("비교 결과 표")
            st.dataframe(
                compare_df[[
                    "입력 도시", "분석 도시", "국가",
                    "총 발전량(kWh)", "총 소비량(kWh)", "자급률(%)", "외부전력 비율(%)",
                    "평균 기온(°C)", "평균 구름량(%)", "평균 온도 보정계수",
                    "경사각 보정계수", "평균 방향 보정계수"
                ]],
                use_container_width=True
            )

            st.subheader("도시별 자급률 비교")
            self_df = compare_df.sort_values("자급률(%)", ascending=False)

            chart_self = alt.Chart(self_df).mark_bar().encode(
                x=alt.X("자급률(%):Q", title="자급률 (%)"),
                y=alt.Y("입력 도시:N", sort="-x", title="도시"),
                tooltip=["입력 도시", "자급률(%)", "총 발전량(kWh)", "총 소비량(kWh)"]
            ).properties(height=300)

            st.altair_chart(chart_self, use_container_width=True)

            st.subheader("도시별 외부전력 비율 비교")
            grid_df = compare_df.sort_values("외부전력 비율(%)", ascending=True)

            chart_grid = alt.Chart(grid_df).mark_bar().encode(
                x=alt.X("외부전력 비율(%):Q", title="외부전력 비율 (%)"),
                y=alt.Y("입력 도시:N", sort="x", title="도시"),
                tooltip=["입력 도시", "외부전력 비율(%)", "자급률(%)"]
            ).properties(height=300)

            st.altair_chart(chart_grid, use_container_width=True)

            st.subheader("도시별 총 발전량 비교")
            power_df = compare_df.sort_values("총 발전량(kWh)", ascending=False)

            chart_power = alt.Chart(power_df).mark_bar().encode(
                x=alt.X("총 발전량(kWh):Q", title="총 발전량 (kWh)"),
                y=alt.Y("입력 도시:N", sort="-x", title="도시"),
                tooltip=["입력 도시", "총 발전량(kWh)", "평균 기온(°C)", "평균 구름량(%)"]
            ).properties(height=300)

            st.altair_chart(chart_power, use_container_width=True)

            st.subheader("비교 결과 요약")

            best_self = compare_df.sort_values("자급률(%)", ascending=False).iloc[0]
            worst_self = compare_df.sort_values("자급률(%)", ascending=True).iloc[0]
            best_power = compare_df.sort_values("총 발전량(kWh)", ascending=False).iloc[0]

            st.write(f"• 자급률이 가장 높은 도시는 **{best_self['입력 도시']}** ({best_self['자급률(%)']}%) 입니다.")
            st.write(f"• 자급률이 가장 낮은 도시는 **{worst_self['입력 도시']}** ({worst_self['자급률(%)']}%) 입니다.")
            st.write(f"• 총 발전량이 가장 높은 도시는 **{best_power['입력 도시']}** ({best_power['총 발전량(kWh)']} kWh) 입니다.")

    except requests.exceptions.RequestException as e:
        st.error(f"API 요청 중 오류가 발생했습니다: {e}")
    except Exception as e:
        st.error(f"오류가 발생했습니다: {e}")

else:
    st.info("왼쪽 사이드바에서 조건을 설정한 뒤 '분석 시작'을 눌러주세요.")