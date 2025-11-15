from bs4 import BeautifulSoup
import requests

#page_to_scrape = requests.get("http://quotes.toscrape.com")
#soup = BeautifulSoup(page_to_scrape.text, "html.parser") 
#quotes = soup.find_all("span", attrs={"class":"text"})
#authors = soup.find_all("small", attrs={"class":"author"})

#for quote, author in zip (quotes, authors):
#    print(quote.text + " - " + author.text)


city_1 = 'Berlin'
city_2 = 'Leipzig'

url = f'https://de.numbeo.com/lebenshaltungskosten/stadt/{city_1}'
page = requests.get(url)
soup = BeautifulSoup(page.content, 'html.parser')
table = soup.find('table', attrs={'class':'data_wide_table'})
rows = table.find_all('tr')

cola_data = rows[7].text.split()

price_1 = cola_data[2]
print(price_1)