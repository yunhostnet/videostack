#!/usr/bin/env python3
import os, sys, re, select, subprocess, io, time, shutil, logging
import urllib.request
from x100.x100config import load_config
from x100.x100util import *
from x100.x100request import http_callback, update_video_status
from x100http import X100HTTP, X100Response
#from transcoder import Transcoder

class Transcoder:
    def __init__(self):
        self.config = load_config('conf/transcoder.conf')
        self.bitrate = int(self.config['segment']['vbitrate']) + int(self.config['segment']['abitrate'])
        self._log_config()

    def upload_start(self, req):
        print("hello")

    def upload_process(self, key, line):
        if key == b'video_id':
            video_id = line.decode().rstrip()
            self.video_id = video_id
            self.init_popen_handler()

            request_info = create_request_info(video_id=self.video_id, status='proceed', bitrate=str(self.bitrate))
            res = http_callback(self.config['url']['update_video_status'], request_info)
            self.log(res, self.video_id, 'update_video_status', None)
        elif key == b'upload':
            self.run_cmd_async(line)

    def upload_finish(self,req):
        print("abcdefgh_done")
        return "your file uploaded."

    def _log_config(self):
        logging.basicConfig(level=logging.INFO)

    def init_popen_handler(self):
        cmd = self.build_cmd(self.video_id)
        print(cmd)
        p = subprocess.Popen(cmd, bufsize=0, stdin=subprocess.PIPE, stdout=subprocess.PIPE, shell=True)
        self.stdout = p.stdout
        self.stdin  = p.stdin
        self.poll   = p.poll()
        self.stdout = non_blocking_handler(self.stdout)
        return

    def run_cmd_async(self, body):
        self.stdin.write(body)
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

                retcode = self.flv2ts(ts_file, target_file)
                if retcode != 0:
                    logging.error("flv2ts flvfile: %s tsfile: %s failed", ts_file, target_file)
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

                info = create_request_info(video_id=self.video_id, snap_image_count=snap_index)

                res  = http_callback(self.config['url']['update_video_snap_image_count'], info)
                self.log(res, self.video_id, 'update_video_snap_image_count', storage_path)
        return

    def flv2ts(self, flvfile, tsfile):
        flv2ts_cmd = cmd = "ffmpeg -i " + flvfile +" -c copy -bsf:v h264_mp4toannexb -y "+ tsfile +" &> /dev/null"
        retcode = subprocess.check_call(flv2ts_cmd, shell=True)
        os.remove(flvfile)
        return retcode

    def segment_request_info(self, filepath, storage_path, file_index):
        create_time  = file_create_time(filepath)
        filesize     = str(file_size(filepath))
        bitrate      = str(self.bitrate)
        video_id     = self.video_id
        hostname     = self.config['base']['hostname']
        storage_path = storage_path
        frame_count  = self.config['segment']['fps_count']
        fragment_id  = file_index

        req_info     = create_request_info(
                            video_id=self.video_id, hostname=self.config['base']['hostname'],\
                            storage_path=storage_path, frame_count=self.config['segment']['fps_count'],\
                            file_size=str(filesize), fragment_id=file_index, bitrate=str(bitrate),\
                            fps=self.config['segment']['fps'], create_time=create_time)
        return req_info

    def running(self):
        return self.poll is None

    def build_cmd(self, video_id):
        storage_dir = self.config['storage']['dir']
        if not os.path.exists(storage_dir):
            os.makedirs(storage_dir)

        tmp_ts_name = storage_dir + '/' + video_id + "_%d.flv"
        tmp_snap_name = storage_dir + '/' + video_id + "_%d.jpg"
        vbitrate = self.config['segment']['vbitrate']
        abitrate = self.config['segment']['abitrate']
        segment_time = self.config['segment']['time']
        cmd = ""
        cmd += "ffmpeg -v verbose -i -"
        cmd += " -filter_complex \""
        cmd += " [0:v:0]fps=15,scale=352:288,split=2[voutA][vtmpB],"
        cmd += " [vtmpB]fps=0.5,scale=176:144[voutB],[0:a:0]asplit=1[aoutA]"
        cmd += "\" "
        cmd += " -map [voutA] -map [aoutA] -c:v libx264 -x264opts bitrate=450:no-8x8dct:bframes=0:no-cabac:weightp=0:no-mbtree:me=dia:no-mixed-refs:partitions=i8x8,i4x4:rc-lookahead=0:ref=1:subme=1:trellis=0"
        cmd += " -c:a libfdk_aac -profile:a aac_he -b:a 16k -f segment -segment_format flv -segment_time 10"
        cmd += " -y "+ tmp_ts_name +" -map [voutB] -y " + tmp_snap_name + " 2>&1"

        if cmd is not None:
            self.cmd = cmd
        else:
            self.cmd = ""

        return cmd

    def log(self, response, video_id, apiname, filename):
        if response['status'] == 'success':
            logging.info("video_id: %s snap: %s callbackApi: %s success", video_id, filename, apiname)
            print("INFO: video_id: %s snap: %s callbackApi: %s success" % (video_id, filename, apiname))
        else:
            logging.error("video_id:%s snap: %s callbackApi: %s  error: %s", video_id, filename, apiname, response['message'])
            print("ERROR: video_id:%s snap: %s callbackApi: %s  error: %s" % (video_id, filename, apiname, response['message']) )
        return

    def __del__(self):
        pass


app = X100HTTP()
app.upload("/upload", Transcoder)
app.run("0.0.0.0", 8080)
