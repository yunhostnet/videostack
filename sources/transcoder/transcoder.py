#!/usr/bin/env python3
import os, sys, re, select, subprocess, io, time, shutil, logging
import urllib.request
import x100mpegts
from x100utils.x100config import load_config
from x100utils.x100util import *
from x100utils.x100request import http_callback, update_video_status

class TranscoderLogger:
    def __init__(self, logfile):
        self.logger = logging.getLogger()
        self.logger.setLevel(logging.INFO)

        handler = logging.FileHandler(logfile)
        handler.setLevel(logging.INFO)

        formatter = logging.Formatter('[%(levelname)s]  %(asctime)s  %(name)s  %(message)s')
        handler.setFormatter(formatter)

        self.logger.addHandler(handler)


class Transcoder:
    def __init__(self):
        self.config  = load_config('conf/transcoder.conf')
        self.bitrate = int(self.config['segment']['vbitrate']) + int(self.config['segment']['abitrate'])
        self.logger  = TranscoderLogger(self.config['log']['path']).logger
        self.video_id = ''

    def upload_start(self, req):
        print("hello")

    def upload_process(self, key, line):
        if key == b'video_id':
            video_id = line.decode().rstrip()
            self.video_id = video_id

            self.init_popen_handler()

            request_info = request_info_serialize(video_id=self.video_id, status='proceed', bitrate=str(self.bitrate))
            res = http_callback(self.config['url']['update_video_status'], request_info)
            self.log(res, self.video_id, 'update_video_status', None)

        elif key == b'upload':
            self.run_cmd_async(line)
            self.write_original_file(line)

    def upload_finish(self,req):
        return "your file uploaded."

    def init_popen_handler(self):
        cmd = build_cmd(self.video_id, self.config)
        print(cmd)
        self.logger.info("ffmpeg_cmd: %s" % cmd)
        self.open_original_file_handler()
        p = subprocess.Popen(cmd, bufsize=0, stdin=subprocess.PIPE, stdout=subprocess.PIPE, shell=True)
        self.stdout = p.stdout
        self.stdin  = p.stdin
        self.poll   = p.poll()
        self.stdout = non_blocking_handler(self.stdout)

    def run_cmd_async(self, body):
        try:
            self.stdin.write(body)
        except:
            request_info = request_info_serialize(video_id=self.video_id, status='failed', bitrate=str(self.bitrate))
            res = http_callback(self.config['url']['update_video_status'], request_info)
            self.log(res, self.video_id, 'update_video_status', 'stdin.write error line 61')
            return 1

        running = self.running()
        while running:
            line = self.stdout.read(-1)
            #segment:'/tmp/a_sd_000030.flv' count:30 endedp=24 drop=0
            if line is None:
                break
            line  = line.decode()
            ts_re = re.search("segment:\'(.*?)\'\s+count:(\d+).*", line)
            if ts_re:
                ts_file        = ts_re.group(1)
                ts_file_index  = ts_re.group(2)
                ts_filename    = ts_file.split('/')[-1]

                (target_file, storage_path) = get_target_file(self.config['storage']['release_dir'], ts_filename, 'ts')

                retcode = flv2ts(ts_file, target_file)
                if retcode != 0:
                    self.logger.error("flv2ts flvfile: %s tsfile: %s failed", ts_file, target_file)
                    continue

                request_info = self.segment_request_info(target_file, storage_path, ts_file_index)
                add_video_segment_url = self.config['url']['add_video_segment']

                res = http_callback( add_video_segment_url, request_info)
                self.log(res, self.video_id, 'add_video_segment', storage_path)

            snap_re = re.search("snap:\'(.*?)\'\s+count:(\d+).*", line)
            if snap_re:
                snap_img_file = snap_re.group(1)
                snap_index    = snap_re.group(2)
                snap_filename = snap_img_file.split('/')[-1]
                (target_file, storage_path) = get_target_file(self.config['storage']['release_dir'], snap_filename, 'snap')

                shutil.move(snap_img_file, target_file)

                info = request_info_serialize(video_id=self.video_id, snap_image_count=snap_index)

                res  = http_callback(self.config['url']['update_video_snap_image_count'], info)
                self.log(res, self.video_id, 'update_video_snap_image_count', storage_path)

    def segment_request_info(self, filepath, storage_path, file_index):
        info = x100mpegts.info(filepath)
        create_time  = info['mtime']
        file_size     = info['file_size']
        bitrate      = info['bitrate']
        frame_count  = info['frame_count']
        fps          = info['fps']

        video_id     = self.video_id
        hostname     = self.config['base']['hostname']
        storage_path = storage_path
        fragment_id  = file_index

        req_info     = request_info_serialize(
                            video_id=video_id, hostname=hostname,\
                            storage_path=storage_path, frame_count=frame_count,\
                            file_size=file_size, fragment_id=file_index, bitrate=bitrate,\
                            fps=fps, create_time=create_time)
        return req_info

    def running(self):
        return self.poll is None

    def log(self, response, video_id, apiname, filename):
        if response['status'] == 'success':
            self.logger.info("[video_id] %s [snap] %s [callbackApi] %s success", video_id, filename, apiname)
        else:
            self.logger.error("[video_id] %s [snap] %s [callbackApi] %s  error: %s", video_id, filename, apiname, response['message'])
        return

    def __del__(self):
        request_info = request_info_serialize(video_id=self.video_id, status='success', bitrate=str(self.bitrate))
        res = http_callback(self.config['url']['update_video_status'], request_info)
        self.log(res, self.video_id, 'update_video_status', None)

    def open_original_file_handler(self):
        filename = self.config['transcode']['dir'] + '/' + self.video_id
        self.original_file_handler = open(filename, 'wb+')

    def write_original_file(self, line):
        self.original_file_handler.write(line)
