#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from telethon import TelegramClient
from telethon.tl.functions.messages import GetHistoryRequest, SearchRequest, SearchGlobalRequest
from telethon.tl.functions.channels import GetParticipantsRequest
from telethon.tl.types import InputMessagesFilterEmpty, ChannelParticipantsSearch, InputPeerEmpty
import asyncio
from datetime import datetime
import time
import sys
import random
from telegram_util import matchKey
from settings import Settings
from cache import Cache
from helper import getClient, addMute, preProcess, getPostIds, getPeerId, getDisplayLink, getLink, deleteAll, unpinTranslated, addChannel, deleteOld, checkUserID, addMuteFromKick
import hashlib
import time

S = Settings()
C = Cache()

def shouldSend(messages, setting):
    if (setting.get('client_name') or 'lani') == 'lani' and setting.get('username') and time.time() < 1622315814:
        print('skip promote')
        return False
    for message in messages:
        if message.action:
            continue
        if time.time() - datetime.timestamp(message.date) < setting.get('wait_minute', 30) * 60:
            # print('need wait due to message', setting['title'], message.raw_text[:20])
            return False # 不打断现有对话
    if time.time() - datetime.timestamp(messages[0].date) > 24 * 60 * 60:
        return True
    for message in messages[:5]:
        if message.from_id and getPeerId(message.from_id) in S.promote_user_ids:
            return False
    return True

def getPromoteMessageHash(message):
    return '%s=%d=%d' % (message.split()[-1].split('/')[-1], datetime.now().month, int(datetime.now().day / 3))

def getMessageHash(post):
    message_id = post.grouped_id
    if post.fwd_from:
        message_id = message_id or post.fwd_from.channel_post
        return '%s=%s' % (str(getPeerId(post.fwd_from.from_id)), str(message_id))
    message_id = message_id or post.id
    return '%d=%d' % (getPeerId(post.peer_id), message_id)

def getHash(target, post):
    return '%s=%s' % (str(target), getMessageHash(post))

async def log(client, group, posts):
    debug_group = await C.get_entity(client, S.credential['debug_group'])
    await client.send_message(debug_group, getLink(group, posts[0]))

def getLogMessage(group, message, client_name):
    id_info, fwd_info, client_info, additional_info = '', '', '', ''
    additional_info = S.getAdditionalInfo(message)
    msg_id = getPeerId(message.from_id)
    if msg_id:
        id_info = '[id](tg://user?id=%d): %d ' % (msg_id, msg_id)
    fwd_from = message.fwd_from and getPeerId(message.fwd_from.from_id)
    if fwd_from:
        fwd_info = 'fwd_id: %d ' % fwd_from
    if client_name != S.default_client_name:
        client_info = '%s ' % client_name
    return '%s%s%s%schat: %s' % (
        id_info,
        fwd_info,
        client_info,
        additional_info,
        getDisplayLink(group, message, S.groups))

def getShaHash(message):
    hash_content = [message.text, message.raw_text]
    if message.file:
        hash_content += [message.file.size, message.file.width, message.file.height]
    return hashlib.sha224(str(hash_content).encode('utf-8')).hexdigest()[:15]

def getItemHashs(message):
    yield 'forward=' + getShaHash(message)
    if message.raw_text:
        core = message.raw_text.split('user:')[0]
        if len(core) > 20:
            yield 'core='+ hashlib.sha224(str(core).encode('utf-8')).hexdigest()[:15]

def hashExistings(item_hashs):
    for item_hash in item_hashs:
        if item_hash and S.existing.get(item_hash):
            return True
    return False

async def logGroupPosts(client, group, group_posts, client_name):
    for message in group_posts.messages[::-1]:
        if S.isNoForwardMessage(message):
            continue
        if not message.raw_text and message.grouped_id:
            continue
        item_hashs = list(getItemHashs(message))
        if hashExistings(item_hashs):
            continue
        tier = S.getTier(message)
        if tier == 3: # save time
            continue
        forward_group = await C.get_entity(client, S.credential['tiers'][tier])
        post_ids = list(getPostIds(message, group_posts.messages))
        try:
            await client.forward_messages(forward_group, post_ids, group)
        except:
            ...
        log_message = getLogMessage(group, message, client_name)
        try:
            await client.send_message(forward_group, log_message, link_preview=False)
        except Exception as e:
            print('forward fail', str(e), tier, client_name, log_message)
            continue
        for item_hash in item_hashs:
            S.existing.update(item_hash, 1)

async def trySend(client, group, subscription, post):
    if time.time() - datetime.timestamp(post.date) < 5 * 60 * 60:
        return
    item_hash = getHash(group.id, post)
    if time.time() - S.message_log.get(getMessageHash(post), 0) < 12 * 60 * 60:
        return
    if S.existing.get(item_hash):
        return
    if S.shouldExclude(post):
        return
    post_ids = list(getPostIds(post, C.getPostsCached(subscription)))
    channel = await C.getChannel(client, subscription, S)
    S.existing.update(item_hash, -1)
    try:
        results = await client.forward_messages(group, post_ids, channel)
    except Exception as e:
        print('telegram_promote forward fail', group.title, subscription, post_ids, str(e))
        return
    print('promoted!', group.title)
    S.my_messages.add('%d_%d' % (group.id, results[0].id))
    await log(client, group, results)
    S.existing.update(item_hash, int(time.time()))
    return True

async def promoteSingle(client, group, setting):
    if setting.get('keys'):
        for subscription in S.all_subscriptions:
            posts = await C.getPosts(client, subscription, S)
            for post in posts:
                if not matchKey(post.raw_text, setting.get('keys')):
                    continue
                result = await trySend(client, group, subscription, post)
                if result:
                    return result

    for subscription in setting.get('subscriptions', []):
        posts = await C.getPosts(client, subscription, S)
        for post in posts[:22]:
            result = await trySend(client, group, subscription, post)
            if result:
                return result

    if setting.get('subscriptions'):
        print('nothing to promote: ' + group.title)

    if not setting.get('message_loop_hard_promote'):
        return
    message = S.getPromoteMessage()
    item_hash = '%s=%s' % (str(group.id), getPromoteMessageHash(message))
    if S.existing.get(item_hash):
        return
    result = await client.send_message(group, message)
    print('promoted!', group.title)
    await log(client, group, [result])
    S.message_loop.inc('message_loop_hard_promote', 1)
    S.existing.update(item_hash, int(time.time()))
    return result

def getPurpose(promoted, setting, gid):
    if setting.get('always_log'):
        return ['log'] # if later on we have two purpose group, we need to change here
    if promoted or not setting.get('promoting') or not S.shouldSendToGroup(gid, setting):
        return []
    return ['promote']

async def process(clients):
    targets = list(S.groups.items())
    random.shuffle(targets)
    promoted = False
    for gid, setting in targets:
        if setting.get('kicked'):
            continue
        client_name, client = getClient(clients, setting)
        try:
            group = await client.get_entity(gid)
        except Exception as e:
            print('telegram_promote Error group fetching fail', gid, setting, str(e))
            continue
        purpose = getPurpose(promoted, setting, gid)
        if not purpose:
            continue
        
        group_posts = await client(GetHistoryRequest(peer=group, limit=100,
            offset_date=None, offset_id=0, max_id=0, min_id=0, add_offset=0, hash=0))
        if 'promote' in purpose and shouldSend(group_posts.messages, setting):
            result = await promoteSingle(client, group, setting)
            if result:
                promoted = True
        await logGroupPosts(client, group, group_posts, client_name)

async def run():
    start_time = time.time()
    clients = {}
    for user, setting in S.credential['users'].items():
        client = TelegramClient('session_file_' + user, S.credential['api_id'], S.credential['api_hash'])
        await client.start(password=setting.get('password'))
        clients[user] = client
        await client.get_dialogs()
    await addMute(clients[S.default_client_name], S)
    await addMuteFromKick(clients, S)
    await deleteAll(clients, S)
    await checkUserID(clients, S, C)
    # await deleteOld(clients, S)
    await preProcess(clients, S.groups)
    await addChannel(clients, S)
    await process(clients)
    await unpinTranslated(clients['yun'])
    for _, client in clients.items():
        await client.disconnect()

def passFilter(text):
    return True
    # if not text:
    #     return False
    # if '堕胎' in text:
    #     return True
    # if '国' in text and '女' in text:
    #     return True
    # return False

async def dialogs(user='lani'):
    setting = S.credential['users'][user]
    client = TelegramClient('session_file_' + user, S.credential['api_id'], S.credential['api_hash'])
    await client.start(password=setting.get('password'))
    result = await client.get_dialogs()
    for group in result:
        try:
            group.entity.participants_count
            group.entity.megagroup
        except:
            continue
        if 0 <= group.entity.participants_count < 300 or group.entity.id in S.groups.keys():
            continue
        if not group.entity.megagroup:
            continue
        username = None
        try:
            username = group.entity.username
        except:
            ...
        print(group.title, group.entity.participants_count, group.id, username)
    await client.disconnect()

async def getMember():
    user = 'lani'
    setting = S.credential['users'][user]
    client = TelegramClient('session_file_' + user, S.credential['api_id'], S.credential['api_hash'])
    await client.start(password=setting.get('password'))
    group = await client.get_entity('https://t.me/brewnote2019') # 1177113440
    print(group.id)
    participants = await client(GetParticipantsRequest(
        group, ChannelParticipantsSearch('jvsdn'), 0, 100, 0
    ))
    for user in participants.users:
        print(user)
        print(user.id) # 788216831

async def testDelete():
    client_name = 'yun'
    setting = S.credential['users'][client_name]
    client = TelegramClient('session_file_' + client_name, S.credential['api_id'], S.credential['api_hash'])
    await client.start(password=setting.get('password'))
    result = await client.get_dialogs()
    await deleteAll([client], S)
    await client.disconnect()

async def test(): 
    client_name = 'yun'
    setting = S.credential['users'][client_name]
    client = TelegramClient('session_file_' + client_name, S.credential['api_id'], S.credential['api_hash'])
    await client.start(password=setting.get('password'))
    result = await client(SearchGlobalRequest(
        q='你是个病人',           # What to search for
        filter=InputMessagesFilterEmpty(),  # Filter to use (maybe filter for media)
        min_date=None,  # Minimum date
        max_date=None,  # Maximum date
        offset_id=0,    # ID of the message to use as offset
        limit=50,       # How many results
        offset_rate=0,
        offset_peer=InputPeerEmpty()
    ))
    print(result)
    await client.disconnect()

async def debug():
    client_name = 'yun'
    setting = S.credential['users'][client_name]
    client = TelegramClient('session_file_' + client_name, S.credential['api_id'], S.credential['api_hash'])
    await client.start(password=setting.get('password'))
    await client.get_dialogs()
    debug_channel = await client.get_entity(1155448058)
    group_posts = await client(GetHistoryRequest(peer=debug_channel, limit=30,
        offset_date=None, offset_id=0, max_id=0, min_id=0, add_offset=0, hash=0))
    message = group_posts.messages[0]
    print(S.getTier(message))
    await client.disconnect()
        
async def search(search_user_id):
    client_name = 'lani'
    setting = S.credential['users'][client_name]
    client = TelegramClient('session_file_' + client_name, S.credential['api_id'], S.credential['api_hash'])
    await client.start(password=setting.get('password'))
    result = await client.get_dialogs()
    user = await client.get_entity(search_user_id)

    forward_group = await C.get_entity(client, S.credential['info_log'])
    for item in result:
        group = await client.get_entity(item.id)
        filter = InputMessagesFilterEmpty()
        try:
            result = await client(SearchRequest(
                peer=group,     # On which chat/conversation
                q='',           # What to search for
                filter=filter,  # Filter to use (maybe filter for media)
                min_date=None,  # Minimum date
                max_date=None,  # Maximum date
                offset_id=0,    # ID of the message to use as offset
                add_offset=0,   # Additional offset
                limit=1000,       # How many results
                max_id=0,       # Maximum message ID
                min_id=0,       # Minimum message ID
                from_id=user,
                hash=0
            ))
        except:
            continue
        username = None
        try:
            username = group.username
        except:
            ...
        for message in result.messages:
            try:
                await client.forward_messages(forward_group, message.id, group)
                log_message = getLogMessage(group, message, client_name)
                await client.send_message(forward_group, log_message, link_preview=False)
            except Exception as e:
                print(e)
                print(message)
    await client.disconnect()
    
if __name__ == "__main__":
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    r = loop.run_until_complete(run())
    loop.close()