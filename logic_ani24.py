# -*- coding: utf-8 -*-
#########################################################
# python
import os
import sys
import traceback
import logging
import threading
import time
import re
# third-party
import requests
from lxml import html

# sjva 공용
from framework import db, scheduler, path_data
from framework.job import Job
from framework.util import Util
from framework.logger import get_logger

# 패키지
from .plugin import package_name, logger
from .model import ModelSetting
from .logic_queue import LogicQueue

#########################################################


class LogicAni24(object):
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/71.0.3578.98 Safari/537.36',
        'Accept' : 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,image/apng,*/*;q=0.8',
        'Accept-Language' : 'ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7'
    }

    session = None
    referer = None
    current_data = None

    @staticmethod
    def get_html(url):
        try:
            if LogicAni24.session is None:
                LogicAni24.session = requests.Session()
            LogicAni24.headers['referer'] = LogicAni24.referer
            LogicAni24.referer = url
            page = LogicAni24.session.get(url, headers=LogicAni24.headers)
            return page.content.decode('utf8')
        except Exception as e:
            logger.error('Exception:%s', e)
            logger.error(traceback.format_exc())

    @staticmethod
    def get_video_url(episode_id):
        try:
            url = '%s/ani_view/%s.html' % (ModelSetting.get('ani24_url'), episode_id)
            data = LogicAni24.get_html(url)
            tree = html.fromstring(data)
            tag = tree.xpath('//div[@class="qwgqwf"]')
            if tag:
                title = tag[0].text_content().strip().encode('utf8')
            else:
                return None
            url2 = 'https://fileiframe.com/ani_video4/%s.html?player=' % episode_id
            #logger.debug(url2)
            data = LogicAni24.get_html(url2)

            #logger.debug(data)
            #tmp = 'sources: [{"file":"'
            #idx1 = data.find(tmp) + len(tmp)
            #idx2 = data.find('"', idx1)
            #video_url = data[idx1:idx2]
            video_url = None
            try:
                tmp = "video.src = '"
                idx1 = data.find(tmp) + len(tmp)
                idx2 = data.find("'", idx1)
                video_url = data[idx1:idx2]
                logger.debug(video_url)
            except:
                pass
            if video_url is None:
                tmp = 'sources: [{"file":"'
                idx1 = data.find(tmp) + len(tmp)
                idx2 = data.find('"', idx1)
                video_url = data[idx1:idx2]
            logger.debug(video_url)
            try:
                if video_url.find('/redirect.php') != -1:
                    video_url = video_url.split('/redirect.php')[0] + video_url.split('path=')[1].replace('%2f', '/').replace('%2F', '/')
            except:
                pass
            return video_url
        except Exception as e:
            logger.error('Exception:%s', e)
            logger.error(traceback.format_exc())


    @staticmethod
    def get_title_info(code):
        try:
            if LogicAni24.current_data is not None and LogicAni24.current_data['code'] == code and LogicAni24.current_data['ret']:
                return LogicAni24.current_data
            url = '%s/ani_list/%s.html' % (ModelSetting.get('ani24_url'), code)
            data = LogicAni24.get_html(url)
            tree = html.fromstring(data)

            data = {}
            data['code'] = code
            data['ret'] = False
            tmp = tree.xpath('//h1[@class="ani_info_title_font_box"]')[0].text_content().strip().encode('utf8')
            match = re.compile(r'(?P<season>\d+)기').search(tmp)
            if match:
                data['season'] = match.group('season')
            else:
                data['season'] = '1'
            data['title'] = tmp.replace(data['season']+u'기', '').strip()
            data['title'] = Util.change_text_for_use_filename(data['title']).replace('OVA', '').strip()
            try:
                data['poster_url'] = 'https:' + tree.xpath('//div[@class="ani_info_left_box"]/img')[0].attrib['src']
                data['detail'] = []
                tmp = tree.xpath('//div[@class="ani_info_right_box"]/div')
                for t in tmp:
                    detail = t.xpath('.//span')
                    data['detail'].append({detail[0].text_content().strip():detail[-1].text_content().strip()})
            except:
                data['detail'] = [{'정보없음':''}]
                data['poster_url'] = None

            tmp = tree.xpath('//span[@class="episode_count"]')[0].text_content().strip()
            match = re.compile(r'\d+').search(tmp)
            if match:
                data['episode_count'] = match.group(0)
            else:
                data['episode_count'] = '0'

            data['episode'] = []
            tags = tree.xpath('//div[@class="ani_video_list"]/a')
            re1 = re.compile(r'ani_view\/(?P<code>\d+)\.html')
            
            for t in tags:
                entity = {}
                entity['code'] = re1.search(t.attrib['href']).group('code')
                data['episode'].append(entity)
                tmp = t.xpath('.//img')[0]
                entity['image'] = 'https:' + tmp.attrib['src']
                tmp = t.xpath('.//div[2]/div')
                entity['title'] = tmp[0].text_content().strip().encode('utf8')
                entity['date'] = tmp[1].text_content().strip()
                entity['filename'] = LogicAni24.get_filename(data['title'], entity['title'],entity['date'])
            data['ret'] = True
            LogicAni24.current_data = data
            return data
        except Exception as e:
            logger.error('Exception:%s', e)
            logger.error(traceback.format_exc())
            data['log'] = str(e)
            return data
    
    @staticmethod
    def get_filename(maintitle, title, date):
        try:
            match = re.compile(r'(?P<title>.*?)\s?((?P<season>\d+)기)?\s?((?P<epi_no>\d+)화)').search(title)
            if match:
                if match.group('season') is not None:
                    season = int(match.group('season'))
                    if season < 10:
                        season = '0%s' % season
                    else:
                        season = '%s' % season
                else:
                    season = '01'

                epi_no = int(match.group('epi_no'))
                if epi_no < 10:
                    epi_no = '0%s' % epi_no
                else:
                    epi_no = '%s' % epi_no

                #date 옵션
                if ModelSetting.get('include_date') == 'True':
                    if ModelSetting.get('date_option') == '1':
                        date_str = '.%s' % date
                    elif ModelSetting.get('date_option') == '0':
                        date_str = '.' + date[2:4] + date[5:7] + date[8:10] 
                else:
                    date_str = ''
                #title_part = match.group('title').strip()
                ret = '%s.S%sE%s%s.720p-SA.mp4' % (maintitle, season, epi_no, date_str)
            else:
                logger.debug('NOT MATCH')
                ret = '%s.720p-SA.mp4' % title
            
            return Util.change_text_for_use_filename(ret)
        except Exception as e:
            logger.error('Exception:%s', e)
            logger.error(traceback.format_exc())


    @staticmethod
    def apply_new_title(new_title):
        try:
            ret = {}
            if LogicAni24.current_data is not None:
                new_title = Util.change_text_for_use_filename(new_title)
                LogicAni24.current_data['title'] = new_title
                for data in LogicAni24.current_data['episode']:
                    tmp = data['filename'].split('.')
                    tmp[0] = new_title
                    data['filename'] = '.'.join(tmp)
                return LogicAni24.current_data
            else:
                ret['ret'] = False
                ret['log'] = 'No current data!!'
        except Exception as e:
            logger.error('Exception:%s', e)
            logger.error(traceback.format_exc())
            ret['ret'] = False
            ret['log'] = str(e)
        return ret

    @staticmethod
    def get_info_by_code(code):
        try:
            if LogicAni24.current_data is not None:
                for t in LogicAni24.current_data['episode']:
                    if t['code'] == code:
                        return t
        except Exception as e:
            logger.error('Exception:%s', e)
            logger.error(traceback.format_exc())
    