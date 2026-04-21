from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup


BASE_URL = "https://www.atmovies.com.tw"
NEXT_URL = "https://www.atmovies.com.tw/movie/next/"


def fetch_upcoming_movies():
    response = requests.get(
        NEXT_URL,
        timeout=15,
        headers={"User-Agent": "Mozilla/5.0"},
    )
    response.encoding = response.apparent_encoding or "utf-8"

    soup = BeautifulSoup(response.text, "html.parser")
    movies = []

    for item in soup.select(".filmListAllX li"):
        title_link = item.select_one(".filmtitle a")
        if not title_link:
            continue

        title = title_link.get_text(strip=True)
        hyperlink = urljoin(BASE_URL, title_link.get("href", ""))

        if title and hyperlink:
            movies.append({"title": title, "url": hyperlink})

    return movies


if __name__ == "__main__":
    for movie in fetch_upcoming_movies():
        print(movie["title"])
        print(movie["url"])
        print()
