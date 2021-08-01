import yaml
from telethon.tl.functions.messages import GetHistoryRequest, SearchRequest
from telethon.tl.types import InputMessagesFilterEmpty
from telegram_util import matchKey, isCN, isInt
import datetime
from telethon import types

def getLinkFromId(group, message_id):
    try:
        if group.username:
            return 'https://t.me/%s/%d' % (group.username, message_id)
    except:
        ...
    return 'https://t.me/c/%s/%d' % (group.id, message_id)

def getLink(group, message):
    return getLinkFromId(group, message.id)

def getClient(clients, setting):
    client_name = setting.get('client_name') or next(iter(clients.keys()))
    return client_name, clients[client_name]

def getPostIds(target_post, posts):
    if target_post.grouped_id:
        for post in posts[::-1]:
            if post.grouped_id == target_post.grouped_id:
                yield post.id
    else:
        yield target_post.id

def getPeerId(peer_id):
    for method in [lambda x: x.channel_id, 
        lambda x: x.chat_id, lambda x: x.user_id]:
        try:
            return method(peer_id)
        except:
            ...

async def unpinTranslated(client):
    await client.get_dialogs()
    chat = await client.get_entity(1386450222)
    messages = await client.get_messages(chat, filter=types.InputMessagesFilterPinned(), limit=500)
    for message in messages:
        if not message.raw_text:
            continue
        if matchKey(message.raw_text, ['已完成', '已翻译']):
            try:
                await client.unpin_message(chat, message.id)
            except Exception as e:
                print(e)
                return

async def deleteSingle(client, message):
    entity = await client.get_entity(getPeerId(message.peer_id))
    forward_group = await client.get_entity(1223777401)
    message_link = getLink(entity, message)
    if not message.grouped_id:
        try:
            await client.forward_messages(forward_group, message.id, entity)
            await client.send_message(forward_group, message_link)
            await client.delete_messages(entity, message.id)
            return 1
        except Exception as e:
            # print('delete failed', str(e), message_link)
            return 0
    messages = await client.get_messages(entity, min_id = message.id, max_id = message.id + 10)
    result = [message]
    for post in messages:
        if post.grouped_id and post.grouped_id == message.grouped_id:
            result.append(post)
    final_result = 0
    for post in result:
        try:
            await client.forward_messages(forward_group, post.id, entity)
            await client.delete_messages(entity, post.id)
            final_result += 1
        except Exception as e:
            # print('delete failed', str(e), message_link)
            ...
    await client.send_message(forward_group, message_link)
    return final_result

def getDisplayLink(group, message, groups):
    invitation_link = groups.get(group.id, {}).get('invitation_link')
    suffix = ''
    if message.reply_to and message.reply_to.reply_to_msg_id:
        suffix += ' [主贴](%s)' % getLinkFromId(group, message.reply_to.reply_to_msg_id)
    if invitation_link:
        suffix += ' [进群](%s)' % invitation_link
    return '[%s](%s)%s' % (group.title, getLink(group, message), suffix)

async def addChannelSingle(clients, text, S):
    client_names = list(clients.keys())
    client_names.remove('yun')
    client_names.append('yun')
    group = None
    try:
        text = int(text)
    except:
        ...
    for client_name in client_names:
        try:
            group = await clients[client_name].get_entity(text)
            break
        except:
            ...
    if not group:
        return 'group not find'
    if group.id in S.groups:
        return 'group exists'
    setting = {'client_name': client_name, 'promoting': 0, 'kicked': 0}
    if group.username:
        setting['username'] = group.username
    if 'joinchat' in str(text):
        setting['invitation_link'] = text
    setting['title'] = group.title
    S.groups[group.id] = setting
    with open('groups.yaml', 'w') as f:
        f.write(yaml.dump(S.groups, sort_keys=True, indent=2, allow_unicode=True)) 
    return 'success'

async def addChannel(clients, S):
    client = clients['yun']
    channel = await client.get_entity(1475165266)
    group_posts = await client(GetHistoryRequest(peer=channel, limit=30,
            offset_date=None, offset_id=0, max_id=0, min_id=0, add_offset=0, hash=0))
    count = 0
    for message in group_posts.messages:
        if not message.raw_text or message.raw_text.startswith('done'):
            continue
        result = await addChannelSingle(clients, message.raw_text, S)
        await client.edit_message(
            channel,
            message.id,
            text = 'done %s: %s' % (message.raw_text, result))

async def addMuteFromKick(clients, S):
    client = clients['yun']
    channel = await client.get_entity(1321042743)
    group_posts = await client(GetHistoryRequest(peer=channel, limit=30,
            offset_date=None, offset_id=0, max_id=0, min_id=0, add_offset=0, hash=0))
    count = 0
    for message in group_posts.messages:
        mute_key = message.raw_text or ''
        mute_key = mute_key.split(':')[0].split()[-1]
        if not isInt(mute_key) or int(mute_key) < 1000:
            continue
        if mute_key not in S.mute_keywords:
            S.mute_keywords.append(mute_key)
            count += 1
    S.save()
    if count: 
        channel = await client.get_entity(S.mute_channel_id)
        await client.send_message(channel, 'mute id added: %d from kick log' % count)

async def addMute(client, S):
    channel = await client.get_entity(S.mute_channel_id)
    group_posts = await client(GetHistoryRequest(peer=channel, limit=30,
            offset_date=None, offset_id=0, max_id=0, min_id=0, add_offset=0, hash=0))
    count = 0
    for message in group_posts.messages:
        if not message.raw_text or message.raw_text.startswith('mute id added:'):
            continue
        mute_key = message.raw_text
        if not isCN(mute_key) and len(mute_key) < 3:
            continue
        if isInt(mute_key):
            mute_key = int(mute_key)
        if mute_key not in S.mute_keywords:
            S.mute_keywords.append(mute_key)
            count += 1
    S.save()
    if count: 
        await client.send_message(channel, 'mute id added: ' + str(count))

async def deleteTarget(client, target):
    if len(target) < 5:
        return 0
    dialogs = await client.get_dialogs()
    result = []
    for dialog in dialogs:
        if type(dialog.entity).__name__ == 'User':
            continue
        try:
            if dialog.entity.participants_count < 20:
                continue
        except:
            print(dialog)
            continue
        messages = await client.get_messages(entity=dialog.entity, search=target, limit=50)
        messages = [message for message in messages if target in message.text]
        result += messages
    result = [message for message in result if target in message.text]    
    result = [message for message in result if not matchKey(message.text, ['【保留】', '【不删】'])]
    if len(result) > 200:
        return 0
    final_result = 0
    for message in result:
        final_result += await deleteSingle(client, message)
    return final_result

async def deleteOldForGroup(client, group):
    user = await client.get_me()
    result = await client(SearchRequest(
        peer=group,     # On which chat/conversation
        q='',           # What to search for
        filter=InputMessagesFilterEmpty(),  # Filter to use (maybe filter for media)
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
    max_id = None
    count = 0
    for message in result.messages:
        if not max_id:
            max_id = message.id
            continue
        if int((datetime.datetime.now(datetime.timezone.utc) - message.date).total_seconds()) < 60 * 60 * 24 * 2:
            continue
        if max_id - message.id < 50:
            continue
        if not message.from_id or getPeerId(message.from_id) != user.id:
            continue
        result = await deleteSingle(client, message)
        count += result
    return count

async def deleteOld(client_map, S):    
    count = 0 
    # 暂时不用，删除所有旧历史
    # for client_name, client in client_map.items():
    #     groups = await client.get_dialogs()
    #     for group in groups:
    #         result = await deleteOldForGroup(client, group.entity)
    #         count += result
    # 这段是删除特定promote群组旧历史
    # for gid in S.groups:
    #     for client_name, client in client_map.items():
    #         try:
    #             group = await client.get_entity(gid)
    #         except:
    #             continue
    #         if not group.megagroup:
    #             continue
    #         result = await deleteOldForGroup(client, group)
    #         count += result
    if count != 0:
        print('deleted old message:', count)

async def checkUserID(client_map, S, C):
    client = client_map['yun']
    channel = await client.get_entity(S.check_id_channel_id)
    group_posts = await client(GetHistoryRequest(peer=channel, limit=30,
            offset_date=None, offset_id=0, max_id=0, min_id=0, add_offset=0, hash=0))
    for message in group_posts.messages:
        text = message.raw_text
        if not text:
            continue
        if not text.startswith('https://t.me'):
            continue
        if len(text.split()) > 1:
            continue
        target_message_id = int(text.split('/')[-1])
        if len(text.split('/')) == 5:
            target_channel_key = '/'.join(text.split('/')[:-1])
            for _, tmp_client in client_map.items():
                try:
                    await C.getPosts(tmp_client, target_channel_key, S) # to populate id map
                    target_channel = await C.getChannel(tmp_client, target_channel_key, S)
                    break
                except:
                    ...
        else:
            target_channel_id = int(text.split('/')[-2])
            for _, tmp_client in client_map.items():
                try:
                    target_channel = await tmp_client.get_entity(target_channel_id)
                    break
                except:
                    ...
        target_message = await tmp_client.get_messages(target_channel, ids=target_message_id)
        user_id = getPeerId(target_message.from_id)
        await client.edit_message(
            channel,
            message.id,
            text = 'done: %s user_id: %d' % (text, user_id))

async def deleteAll(client_map, S):
    client_names = list(client_map.keys())
    client_names.remove('yun')
    client_names = ['yun'] + client_names
    clients = [client_map[name] for name in client_names]
    client = clients[0]
    channel = await client.get_entity(S.delete_all_channel_id)
    group_posts = await client(GetHistoryRequest(peer=channel, limit=30,
            offset_date=None, offset_id=0, max_id=0, min_id=0, add_offset=0, hash=0))
    for message in group_posts.messages:
        if not message.raw_text:
            continue
        if message.raw_text.startswith('done'):
            break
        result = 0
        for tmp_client in clients:
            result += await deleteTarget(tmp_client, message.raw_text)
        await client.edit_message(
            channel,
            message.id,
            text = 'done: %s deleted: %d' % (message.raw_text, result))

async def preProcess(clients, groups):
    for gid, setting in list(groups.items()):
        try:
            int(gid)
            continue
        except:
            ...
        _, client = getClient(clients, setting)
        group = await client.get_entity(gid)
        if group.username:
            setting['username'] = group.username
        if 'joinchat' in str(gid):
            setting['invitation_link'] = gid
        setting['title'] = group.title
        del groups[gid]
        groups[group.id] = setting
        with open('groups.yaml', 'w') as f:
            f.write(yaml.dump(groups, sort_keys=True, indent=2, allow_unicode=True))