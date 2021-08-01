#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from telethon import TelegramClient
from bs4 import BeautifulSoup
import asyncio
import yaml
import plain_db
from telegram_util import isCN
import webgram

with open('credential') as f:
    credential = yaml.load(f, Loader=yaml.FullLoader)

with open('setting') as f:
    setting = yaml.load(f, Loader=yaml.FullLoader)

cache = plain_db.load('cache')

def getNextPost(posts):
    for post in posts[::-1]:
        if post.text and isCN(post.text):
            return post

def getText(post):
    soup = webgram.getPost(setting['src_name'], post.id).text
    source = ''
    for item in soup:
        if item.name == 'a':
            if 'source' in item.text:
                source = item['href']
            item.decompose()
        if item.name == 'br':
            item.replace_with('\n')
    text = soup.text.strip()
    result = text + '\n\n' + source
    return result

async def process(client):
    src = await client.get_entity(setting['src'])
    last_sync = cache.get('last_sync', 0)
    posts = await client.get_messages(src, min_id=last_sync, max_id = last_sync + 100, limit = 100)
    post = getNextPost(posts)
    if not post:
        cache.update('last_sync', last_sync + 99)
        return
    text = getText(post)
    dest = await client.get_entity(setting['dest'])
    # '/fttt ' + text
    # await client.send_message(dest, text) # link_preview = False?
    cache.update('last_sync', post.id)
        
async def run():
    client = TelegramClient('session_file', credential['api_id'], credential['api_hash'])
    await client.start(password=credential['password'])
    await process(client)
    await client.disconnect()
    
if __name__ == "__main__":
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    cache.update('last_sync', 0) # testing
    for _ in range(100):
        loop.run_until_complete(run())
    loop.close()