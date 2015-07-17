from flask import Flask,request,make_response
import time,redis,x100idgen

app = Flask(__name__)

@app.route("/interface/video_uuid_get")
def video_uuid_get():
    userAgent   = request.headers.get('User-Agent')
    ip          = request.remote_addr
    millisecond = int(round(time.time() * 1000))
 
    response  = make_response()
    response.headers['Access-Control-Allow-Methods'] = 'GET'
    response.headers['Access-Control-Allow-Origin'] = '*'
    
    hash_string = ip + userAgent + millisecond
    idgen       = x100idgen.IdGen()
    uuid        = idgen.gen_id(hash_string)
    
    response.data = uuid
    return response

@app.route("/interface/video_uuid_status_set")
def video_uuid_status_set():
    uuid   = request.args.get('uuid')
    status = request.args.get('status')

    response  = make_response()
    response.headers['Access-Control-Allow-Methods'] = 'GET'
    response.headers['Access-Control-Allow-Origin'] = '*'
    
    if not uuid or not status:
        response.data = '{"status":"failed", "message":"uuid or status is empty"}'
        return response

    value = ''
    r     = redis_connect()
    ret   = r.hget("x100speed_hash_uuid", uuid)
    if not ret:
        value = status + '|'
    else: 
        infor        = ret.decode()
        string_split = infor.split('|')
        print(string_split)
        value = status + '|' + string_split[1]

    r.hset('x100speed_hash_uuid', uuid, value)

    response.data = '{"status":"success", "message":""}'
    return response

@app.route("/interface/video_uuid_snap_count_set")
def video_uuid_snap_count_set():
    uuid       = request.args.get('uuid')
    snap_count = request.args.get('snap_count')

    response  = make_response()
    response.headers['Access-Control-Allow-Methods'] = 'GET'
    response.headers['Access-Control-Allow-Origin'] = '*'
    
    if not uuid or not snap_count:
        response.data = '{"status":"failed", "message":"uuid or snap_count is empty"}'
        return response

    value = ''
    r     = redis_connect()
    ret   = r.hget("x100speed_hash_uuid", uuid)
    if not ret:
        value = '|' + snap_count
    else:
        infor        = ret.decode()
        string_split = infor.split('|')
        value        = string_split[0] + '|' + snap_count

    r.hset('x100speed_hash_uuid', uuid, value)

    response.data = '{"status":"success", "message":""}'
    return response

@app.route("/interface/video_uuid_segment_add")
def video_uuid_segment_add():
    uuid         = request.args.get('uuid')
    bitrate      = request.args.get('bitrate')
    fragment_id  = request.args.get('fragment_id')
    hostname     = request.args.get('hostname')
    storage_path = request.args.get('storage_path') 
    create_time  = request.args.get('create_time')
    fps          = request.args.get('fps')
    frame_count  = request.args.get('frame_count')
    file_size    = request.args.get('file_size')

    response  = make_response()
    response.headers['Access-Control-Allow-Methods'] = 'GET'
    response.headers['Access-Control-Allow-Origin'] = '*'

    if not uuid or not fragment_id or not hostname or not storage_path \
       or not create_time or not fps or not frame_count or not file_size:
        response.data = '{"status":"failed", "message":"params have error"}'
        return response
    
    sorted_set_key    = 'x100speed_sortedset_uuid_' + bitrate
    sorted_set_score  = create_time
    sorted_set_member = fragment_id + '|' + hostname + '|' + storage_path + '|' + create_time \
                        + '|' + fps + '|' + frame_count + '|' + file_size
    r   = redis_connect()
    ret = r.zadd(sorted_set_key, sorted_set_score, sorted_set_member)
    print(ret)

    response.data = '{"status":"success", "message":""}'
    return response


def redis_connect():
    host='127.0.0.1'
    port=6379
    db=0
    password='foobared'

    r = redis.StrictRedis(host = host, port = port, password = password, db = db)
    return r

if __name__ == "__main__":
    app.debug = True
    app.run(host='0.0.0.0')