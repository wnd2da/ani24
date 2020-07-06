# -*- coding: utf-8 -*-
#########################################################
# python
import os
import sys
import traceback
import logging
import threading
import Queue
import json
import time
from datetime import datetime
# third-party

# sjva 공용
from framework import db, scheduler, path_data
from framework.job import Job
from framework.util import Util
from framework.logger import get_logger

# 패키지
from .plugin import package_name, logger
import system
from .model import ModelSetting

#########################################################

class QueueEntity:
    static_index = 1
    entity_list = []

    def __init__(self, info):
        self.entity_id = QueueEntity.static_index
        self.info = info
        self.url = None
        self.ffmpeg_status = -1
        self.ffmpeg_status_kor = u'대기중'
        self.ffmpeg_percent = 0
        self.ffmpeg_arg = None
        self.cancel = False
        self.created_time = datetime.now().strftime('%m-%d %H:%M:%S')
        QueueEntity.static_index += 1
        QueueEntity.entity_list.append(self)

    @staticmethod
    def create(info):
        for e in QueueEntity.entity_list:
            if e.info['code'] == info['code']:
                return
        ret = QueueEntity(info)
        return ret

    @staticmethod
    def get_entity_by_entity_id(entity_id):
        for _ in QueueEntity.entity_list:
            if _.entity_id == entity_id:
                return _
        return None


class LogicQueue(object):
    download_queue = None
    download_thread = None
    current_ffmpeg_count = 0

    @staticmethod
    def queue_start():
        try:
            if LogicQueue.download_queue is None:
                LogicQueue.download_queue = Queue.Queue()
            if LogicQueue.download_thread is None:
                LogicQueue.download_thread = threading.Thread(target=LogicQueue.download_thread_function, args=())
                LogicQueue.download_thread.daemon = True  
                LogicQueue.download_thread.start()
        except Exception as e: 
            logger.error('Exception:%s', e)
            logger.error(traceback.format_exc())

    
    @staticmethod
    def download_thread_function():
        while True:
            try:
                entity = LogicQueue.download_queue.get()
                logger.debug('Queue receive item:%s %s', entity.title_id, entity.episode_id)
                LogicAni.process(entity)
                LogicQueue.download_queue.task_done()    
            except Exception as e: 
                logger.error('Exception:%s', e)
                logger.error(traceback.format_exc())


    @staticmethod
    def download_thread_function():
        import plugin
        while True:
            try:
                while True:
                    if LogicQueue.current_ffmpeg_count < int(ModelSetting.get('max_ffmpeg_process_count')):
                        break
                    #logger.debug(LogicQueue.current_ffmpeg_count)
                    time.sleep(5)
                entity = LogicQueue.download_queue.get()
                if entity.cancel:
                    continue
                
                from .logic_ani24 import LogicAni24
                entity.url = LogicAni24.get_video_url(entity.info['code'])
                if entity.url is None:
                    self.ffmpeg_status_kor = 'URL실패'
                    plugin.socketio_list_refresh()
                    continue

                import ffmpeg
                #max_pf_count = 0 
                save_path = ModelSetting.get('download_path')
                if ModelSetting.get('auto_make_folder') == 'True':
                    program_path = os.path.join(save_path, entity.info['filename'].split('.')[0])
                    save_path = program_path
                try:
                    if not os.path.exists(save_path):
                        os.makedirs(save_path)
                except:
                    logger.debug('program path make fail!!')
                # 파일 존재여부 체크
                if os.path.exists(os.path.join(save_path, entity.info['filename'])):
                    entity.ffmpeg_status_kor = '파일 있음'
                    entity.ffmpeg_percent = 100
                    plugin.socketio_list_refresh()
                    continue
                f = ffmpeg.Ffmpeg(entity.url, entity.info['filename'], plugin_id=entity.entity_id, listener=LogicQueue.ffmpeg_listener, call_plugin=package_name, save_path=save_path)
                f.start()
                LogicQueue.current_ffmpeg_count += 1
                LogicQueue.download_queue.task_done()    
            except Exception as e: 
                logger.error('Exception:%s', e)
                logger.error(traceback.format_exc())

    @staticmethod
    def ffmpeg_listener(**arg):
        #logger.debug(arg)
        import ffmpeg
        refresh_type = None
        if arg['type'] == 'status_change':
            if arg['status'] == ffmpeg.Status.DOWNLOADING:
                pass
            elif arg['status'] == ffmpeg.Status.COMPLETED:
                pass
            elif arg['status'] == ffmpeg.Status.READY:
                pass
        elif arg['type'] == 'last':
            LogicQueue.current_ffmpeg_count += -1
            pass
        elif arg['type'] == 'log':
            pass
        elif arg['type'] == 'normal':
            pass
        if refresh_type is not None:
            pass

        entity = QueueEntity.get_entity_by_entity_id(arg['plugin_id'])
        if entity is None:
            return
        entity.ffmpeg_arg = arg
        entity.ffmpeg_status = int(arg['status'])
        entity.ffmpeg_status_kor = str(arg['status'])
        entity.ffmpeg_percent = arg['data']['percent']
        import plugin
        arg['status'] = str(arg['status'])
        plugin.socketio_callback('status', arg)


    @staticmethod
    def add_queue(info):
        try:
            entity = QueueEntity.create(info)
            if entity is not None:
                LogicQueue.download_queue.put(entity)
                return True
        except Exception as e:
            logger.error('Exception:%s', e)
            logger.error(traceback.format_exc())
        return False


    @staticmethod
    def program_auto_command(req):
        try:
            import plugin
            command = req.form['command']
            entity_id = int(req.form['entity_id'])
            logger.debug('command :%s %s', command, entity_id)
            entity = QueueEntity.get_entity_by_entity_id(entity_id)
            
            ret = {}
            if command == 'cancel':
                if entity.ffmpeg_status == -1:
                    entity.cancel = True
                    entity.ffmpeg_status_kor = "취소"
                    plugin.socketio_list_refresh()
                    ret['ret'] = 'refresh'
                elif entity.ffmpeg_status != 5:
                    ret['ret'] = 'notify'
                    ret['log'] = '다운로드중 상태가 아닙니다.'
                else:
                    idx = entity.ffmpeg_arg['data']['idx']
                    import ffmpeg
                    ffmpeg.Ffmpeg.stop_by_idx(idx)
                    #plugin.socketio_list_refresh()
                    ret['ret'] = 'refresh'
            elif command == 'reset':
                if LogicQueue.download_queue is not None:
                    with LogicQueue.download_queue.mutex:
                        LogicQueue.download_queue.queue.clear()
                    for _ in QueueEntity.entity_list:
                        if _.ffmpeg_status == 5:
                            import ffmpeg
                            idx = _.ffmpeg_arg['data']['idx']
                            ffmpeg.Ffmpeg.stop_by_idx(idx)
                QueueEntity.entity_list = []
                plugin.socketio_list_refresh()
                ret['ret'] = 'refresh'
            elif command == 'delete_completed':
                new_list = []
                for _ in QueueEntity.entity_list:
                    if _.ffmpeg_status_kor in ['파일 있음', '취소']:
                        continue
                    if _.ffmpeg_status != 7:
                        new_list.append(_)
                QueueEntity.entity_list = new_list
                plugin.socketio_list_refresh()
                ret['ret'] = 'refresh'
            
        except Exception as e: 
            logger.error('Exception:%s', e)
            logger.error(traceback.format_exc())
            ret['ret'] = 'notify'
            ret['log'] = str(e)
        return ret

