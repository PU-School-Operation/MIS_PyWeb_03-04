import requests
import json


def get_taichung_accident_roads(limit=10):
    """
    取得台中市肇事路口資料

    Args:
        limit (int): 返回的路口數量，預設前10筆

    Returns:
        list: 肇事路口列表，或包含 error 的字典
    """
    try:
        url = "https://datacenter.taichung.gov.tw/swagger/OpenData/a1b899c0-511f-4e3d-b22b-814982a97e41"
        Data = requests.get(url, timeout=5)
        Data.raise_for_status()

        JsonData = json.loads(Data.text)

        # 按總件數排序，取前 limit 筆
        sorted_roads = sorted(
            JsonData, key=lambda x: int(x.get("總件數", 0)), reverse=True
        )

        result = []
        for item in sorted_roads[:limit]:
            result.append(
                {
                    "路口名稱": item.get("路口名稱", ""),
                    "總件數": item.get("總件數", "0"),
                    "主要肇因": item.get("主要肇因", ""),
                }
            )

        return result
    except Exception as e:
        return {"error": f"發生錯誤：{str(e)}"}


def search_accident_by_road(road_name):
    """
    根據路名查詢肇事資料

    Args:
        road_name (str): 欲查詢的路名

    Returns:
        list: 符合條件的路口列表
    """
    try:
        url = "https://datacenter.taichung.gov.tw/swagger/OpenData/a1b899c0-511f-4e3d-b22b-814982a97e41"
        Data = requests.get(url, timeout=5)
        Data.raise_for_status()

        JsonData = json.loads(Data.text)

        result = []
        for item in JsonData:
            if road_name in item.get("路口名稱", ""):
                result.append(
                    {
                        "路口名稱": item.get("路口名稱", ""),
                        "總件數": item.get("總件數", "0"),
                        "主要肇因": item.get("主要肇因", ""),
                    }
                )

        return result
    except Exception as e:
        return {"error": f"發生錯誤：{str(e)}"}
