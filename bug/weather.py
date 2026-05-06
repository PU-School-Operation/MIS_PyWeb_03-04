import requests
import json


def get_weather(city):
    """
    取得指定縣市的天氣及降雨機率
    
    Args:
        city (str): 縣市名稱
    
    Returns:
        dict: 包含 weather 和 rain 的字典，或 error 訊息
    """
    try:
        city = city.replace("台", "臺")
        token = "rdec-key-123-45678-011121314"
        url = (
            "https://opendata.cwa.gov.tw/api/v1/rest/datastore/F-C0032-001?Authorization="
            + token
            + "&format=JSON&locationName="
            + str(city)
        )
        Data = requests.get(url, timeout=5)
        Data.raise_for_status()
        
        json_data = json.loads(Data.text)
        
        if "records" not in json_data or "location" not in json_data["records"]:
            return {"error": "查無相關資料"}
        
        locations = json_data["records"]["location"]
        if not locations:
            return {"error": "查無相關資料"}
        
        weather = locations[0]["weatherElement"][0]["time"][0]["parameter"]["parameterName"]
        rain = locations[0]["weatherElement"][1]["time"][0]["parameter"]["parameterName"]
        
        return {
            "city": city,
            "weather": weather,
            "rain": rain,
            "error": None
        }
    except Exception as e:
        return {"error": f"發生錯誤：{str(e)}"}
