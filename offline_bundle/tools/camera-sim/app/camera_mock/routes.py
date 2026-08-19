import json
from flask import Response, request, jsonify, render_template_string, stream_with_context

from . import cycctv_bp
from .models import the_list, save_list

MANAGEMENT_HTML = r"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>CCTV Mock</title>
<style>
*{margin:0;padding:0;box-sizing:border-box}
body{font-family:system-ui,sans-serif;background:#f0f2f5;padding:16px;padding-bottom:0;display:flex;flex-direction:column;height:100vh;overflow:hidden}
h2{color:#333;margin-bottom:10px;flex-shrink:0}
.url-bar{background:#fff;border:1px solid #d9d9d9;border-radius:8px;padding:10px 14px;margin-bottom:10px;display:flex;align-items:center;gap:10px;font-size:13px;flex-shrink:0}
.url-bar .label{color:#888;white-space:nowrap;font-weight:500}
.url-bar code{flex:1;color:#1890ff;background:#f5f5f5;padding:6px 10px;border-radius:4px;font-size:13px;word-break:break-all;user-select:all}
.url-bar button{padding:6px 14px;border:none;border-radius:4px;background:#1890ff;color:#fff;cursor:pointer;font-size:12px;white-space:nowrap}
.url-bar button:hover{background:#40a9ff}
.url-bar .copied{background:#52c41a}
.example{color:#888;font-size:12px;margin-bottom:10px;line-height:1.6;flex-shrink:0}
.example code{background:#fff7e6;color:#d48806;padding:2px 6px;border-radius:3px;font-size:12px}
.toolbar{display:flex;gap:10px;margin-bottom:10px;flex-wrap:wrap;align-items:center;flex-shrink:0}
.toolbar input{padding:8px 12px;border:1px solid #d9d9d9;border-radius:6px;font-size:14px;flex:1;min-width:180px}
.toolbar button{padding:8px 16px;border:none;border-radius:6px;cursor:pointer;font-size:13px;font-weight:500;transition:.2s}
.btn-add{background:#1890ff;color:#fff}
.btn-add:hover{background:#40a9ff}
.btn-refresh{background:#52c41a;color:#fff}
.btn-refresh:hover{background:#73d13d}
.info{color:#888;font-size:12px;margin-bottom:8px;flex-shrink:0}
.scroll-area{flex:1;overflow-y:auto;padding-bottom:8px;min-height:0}
.group{margin-bottom:10px}
.group-header{background:#fff;border:1px solid #e8e8e8;border-radius:8px;padding:10px 14px;cursor:pointer;display:flex;align-items:center;gap:10px;user-select:none;transition:.2s}
.group-header:hover{background:#fafafa}
.group-header .arrow{font-size:12px;transition:transform .2s;color:#999}
.group-header.collapsed .arrow{transform:rotate(-90deg)}
.group-header .ip{font-weight:600;color:#333;font-size:14px}
.group-header .count{color:#999;font-size:12px;margin-left:auto}
.group-body{overflow:hidden;transition:max-height .3s ease}
.group-body.collapsed{max-height:0!important}
.card{background:#fff;border:1px solid #f0f0f0;border-top:none;padding:10px 14px;display:flex;align-items:center;gap:10px;flex-wrap:wrap}
.card:first-child{border-top:1px solid #f0f0f0;border-radius:0}
.card:last-child{border-radius:0 0 8px 8px}
.card .name{font-weight:600;min-width:140px;color:#1a1a1a;word-break:break-all}
.card .field{font-size:12px;color:#666;white-space:nowrap}
.card .status{font-weight:700;padding:2px 8px;border-radius:4px;font-size:12px}
.status-true{background:#d9f7be;color:#389e0d}
.status-false{background:#ffd8bf;color:#d4380d}
.status-unknown{background:#fff7e6;color:#d48806}
.card .actions{display:flex;gap:6px;flex-wrap:wrap;margin-left:auto}
.card .actions button{padding:5px 10px;border:1px solid #d9d9d9;border-radius:4px;background:#fff;cursor:pointer;font-size:12px;transition:.2s;white-space:nowrap}
.card .actions button:hover{border-color:#1890ff;color:#1890ff}
.card .actions .btn-remove{color:#ff4d4f;border-color:#ffccc7}
.card .actions .btn-remove:hover{background:#fff1f0;color:#ff4d4f}
.json-panel{flex-shrink:0;border-top:2px solid #e8e8e8;background:#fafafa;padding:0}
.json-panel .json-header{display:flex;align-items:center;justify-content:space-between;padding:8px 14px;cursor:pointer;user-select:none;font-size:13px;font-weight:500;color:#555}
.json-panel .json-header:hover{background:#f0f0f0}
.json-panel .json-header .arrow{font-size:11px;transition:transform .2s}
.json-panel.collapsed .json-header .arrow{transform:rotate(-90deg)}
.json-panel pre{background:#1e1e1e;color:#d4d4d4;padding:10px 14px;margin:0;overflow-x:auto;font-size:12px;line-height:1.5;max-height:200px;overflow-y:auto;border-radius:0}
.json-panel.collapsed pre{display:none}
.modal-overlay{display:none;position:fixed;top:0;left:0;width:100%;height:100%;background:rgba(0,0,0,.45);z-index:1000;justify-content:center;align-items:center}
.modal-overlay.show{display:flex}
.modal-box{background:#fff;border-radius:10px;padding:24px;width:520px;max-width:95vw;max-height:80vh;overflow-y:auto}
.modal-box h3{margin-bottom:16px}
.modal-box label{display:block;margin-bottom:6px;font-weight:500;font-size:13px;color:#333}
.modal-box input,.modal-box textarea,.modal-box select{width:100%;padding:8px;margin-bottom:12px;border:1px solid #d9d9d9;border-radius:5px;font-size:13px}
.modal-box textarea{resize:vertical;min-height:60px}
.modal-box .btn-row{display:flex;gap:8px;justify-content:flex-end}
.modal-box .btn-row button{padding:8px 18px;border:none;border-radius:5px;cursor:pointer;font-size:13px}
.modal-box .btn-save{background:#1890ff;color:#fff}
.modal-box .btn-cancel{background:#f0f0f0;color:#333}
@media(max-width:600px){.card{flex-direction:column;align-items:flex-start}.card .actions{margin-left:0}}
</style>
</head>
<body>
<h2>CCTV Mock</h2>

<div class="url-bar">
    <span class="label">GET URL:</span>
    <code id="apiUrl"></code>
    <button id="copyBtn" onclick="copyUrl()">复制</button>
</div>

<div class="example">
    添加格式: <code>区域-序号@IP</code>，例如: <code>Z-3@10.3.10.21</code>、<code>A-1@192.168.1.100</code>
</div>

<div class="toolbar">
    <input type="text" id="searchInput" placeholder="搜索名称..." oninput="renderList()">
    <button class="btn-add" onclick="showAddModal()">添加条目</button>
    <button class="btn-refresh" onclick="location.reload()">刷新</button>
</div>

<div class="info" id="infoBar"></div>

<div class="scroll-area" id="cardList"></div>

<div class="json-panel" id="jsonPanel">
    <div class="json-header" onclick="toggleJson()">
        <span>JSON 输出预览</span>
        <span class="arrow">&#9660;</span>
    </div>
    <pre id="jsonPreview"></pre>
</div>

<div class="modal-overlay" id="editModal">
    <div class="modal-box">
        <h3 id="modalTitle"></h3>
        <label>状态 (s)</label><select id="editS"><option value="unknown">unknown</option><option value="true">true</option><option value="false">false</option></select>
        <label>时间 (t)</label><input type="text" id="editT">
        <label>坐标 (r)</label><input type="text" id="editR">
        <label>分数 (rs)</label><input type="number" id="editRs">
        <label>标签 (l)</label><textarea id="editL"></textarea>
        <label>机器IP (M)</label><input type="text" id="editM">
        <div class="btn-row">
            <button class="btn-cancel" onclick="closeEditModal()">取消</button>
            <button class="btn-save" onclick="saveEdit()">保存</button>
        </div>
    </div>
</div>

<script>
var REFRESH="{{ refresh }}";
var PREFIX="/api/v1/camera";
var currentData={{ theList|tojson }};
var autoUpdateDisabled={};
var cameraEvents=null;
var syncTimer=null;

document.getElementById("apiUrl").textContent = window.location.origin + PREFIX + "/list-all";

function copyUrl(){
    var t = document.getElementById("apiUrl").textContent;
    var b = document.getElementById("copyBtn");
    var done = function(){
        b.textContent = "已复制";
        b.classList.add("copied");
        setTimeout(function(){b.textContent="复制";b.classList.remove("copied");}, 1500);
    };
    if(navigator.clipboard && navigator.clipboard.writeText){
        navigator.clipboard.writeText(t).then(done).catch(function(){
            fallbackCopy(t, done);
        });
    } else {
        fallbackCopy(t, done);
    }
}
function fallbackCopy(text, cb){
    var ta = document.createElement("textarea");
    ta.value = text;
    ta.style.position = "fixed"; ta.style.left = "-9999px";
    document.body.appendChild(ta);
    ta.select();
    try{document.execCommand("copy");cb();}catch(e){}
    document.body.removeChild(ta);
}

function extractIP(name, item){
    if(item.M && item.M.trim()) return item.M.trim();
    var idx = name.lastIndexOf("@");
    if(idx >= 0 && idx < name.length-1) return name.substring(idx+1);
    return "未分类";
}

function groupByIP(data){
    var groups = {};
    var keys = Object.keys(data);
    for(var i=0;i<keys.length;i++){
        var k=keys[i],v=data[k];
        var ip=extractIP(k,v);
        if(!groups[ip])groups[ip]=[];
        groups[ip].push({name:k,item:v});
    }
    var sorted=[];
    var ips=Object.keys(groups).sort();
    var unclassified=null;
    for(var j=0;j<ips.length;j++){
        var ip=ips[j];
        if(ip==="未分类"){unclassified={ip:ip,entries:groups[ip]};}
        else{sorted.push({ip:ip,entries:groups[ip]});}
    }
    if(unclassified)sorted.push(unclassified);
    return sorted;
}

function renderList(){
    var s=document.getElementById("searchInput").value.toLowerCase();
    var c=document.getElementById("cardList");
    var groups=groupByIP(currentData);
    var h="",total=0,shown=0;
    var allKeys=Object.keys(currentData);
    total=allKeys.length;

    for(var g=0;g<groups.length;g++){
        var group=groups[g];
        var entries=group.entries;
        var bodyH="",groupShown=0;
        for(var i=0;i<entries.length;i++){
            var e=entries[i],k=e.name,v=e.item;
            if(s&&k.toLowerCase().indexOf(s)===-1)continue;
            groupShown++;
            var st=v.s||"unknown";
            var t=v.t?new Date(v.t).toLocaleString():"-";
            var ltext=(v.l||"").replace(/\n/g,"<br>");
            bodyH+='<div class="card">'+
                '<span class="name">'+esc(k)+'</span>'+
                '<span class="status status-'+st+'">'+st+'</span>'+
                '<span class="field">'+t+'</span>'+
                '<span class="field">r:'+(v.r||"0,0")+'</span>'+
                '<span class="field">rs:'+(v.rs||0)+'</span>'+
                '<span class="field">l:'+esc(ltext)+'</span>'+
                '<div class="actions">'+
                '<button onclick="setStatus(\''+esc(k)+'\',\'unknown\')">未知</button>'+
                '<button onclick="setStatus(\''+esc(k)+'\',\'true\')">正常</button>'+
                '<button onclick="setStatus(\''+esc(k)+'\',\'false\')">异常</button>'+
                '<button onclick="setTimeNow(\''+esc(k)+'\')">更新时间</button>'+
                '<button onclick="setAutoUpdate(\''+esc(k)+'\','+(autoUpdateDisabled[k]?'1':'0')+')">'+(autoUpdateDisabled[k]?'开启':'关闭')+'自动更新</button>'+
                '<button onclick="setTimeHourAgo(\''+esc(k)+'\')">设为-1H</button>'+
                '<button onclick="showEditModal(\''+esc(k)+'\')">编辑</button>'+
                '<button class="btn-remove" onclick="removeItem(\''+esc(k)+'\')">删除</button>'+
                '</div></div>';
        }
        if(groupShown===0)continue;
        shown+=groupShown;
        h+='<div class="group">'+
            '<div class="group-header" onclick="toggleGroup(this)">'+
            '<span class="arrow">&#9660;</span>'+
            '<span class="ip">'+esc(group.ip)+'</span>'+
            '<span class="count">'+groupShown+' 条</span>'+
            '</div>'+
            '<div class="group-body" style="max-height:'+(groupShown*80+200)+'px">'+
            bodyH+'</div></div>';
    }
    c.innerHTML=h||'<div style="color:#999;padding:20px;text-align:center">暂无条目，点击"添加条目"开始</div>';
    document.getElementById("infoBar").textContent="显示 "+shown+" / 共 "+total+" 条";
    document.getElementById("jsonPreview").textContent=JSON.stringify({list:currentData},null,2);
}

function toggleGroup(hdr){
    hdr.classList.toggle("collapsed");
    hdr.nextElementSibling.classList.toggle("collapsed");
}

function toggleJson(){
    document.getElementById("jsonPanel").classList.toggle("collapsed");
}

function esc(s){return String(s).replace(/&/g,"&amp;").replace(/"/g,"&quot;").replace(/</g,"&lt;").replace(/>/g,"&gt;").replace(/'/g,"&#39;");}
function refreshState(){
    return Promise.all([fetch(PREFIX+"/list-all"),fetch(PREFIX+"/settings")])
        .then(function(rs){return Promise.all([rs[0].json(),rs[1].json()]);})
        .then(function(data){
            currentData=data[0].list||{};
            autoUpdateDisabled={};
            (data[1].disabled_auto_update||[]).forEach(function(name){autoUpdateDisabled[name]=true;});
            renderList();
        });
}
function apiGet(u){fetch(u).then(function(r){return r.json()}).then(function(){return refreshState();});}
function setStatus(n,s){apiGet(PREFIX+"/list/setStatus/"+encodeURIComponent(n)+"/"+s);}
function setTimeNow(n){apiGet(PREFIX+"/list/setTimeNow/"+encodeURIComponent(n));}
function setTimeHourAgo(n){apiGet(PREFIX+"/list/setTimeHourAgo/"+encodeURIComponent(n));}
function setAutoUpdate(n,enabled){fetch(PREFIX+"/list/set-auto-update/"+encodeURIComponent(n)+"/"+enabled,{method:"POST"}).then(function(r){return r.json()}).then(function(){return refreshState();});}
function removeItem(n){if(!confirm("确定删除 ["+n+"] ?"))return;apiGet(PREFIX+"/list/remove/"+encodeURIComponent(n));}
function showAddModal(){var n=prompt("输入条目名称\n格式: 区域-序号@IP\n例如: Z-3@10.3.10.21");if(!n)return;fetch(PREFIX+"/list/add",{method:"POST",headers:{"Content-Type":"application/x-www-form-urlencoded"},body:"name="+encodeURIComponent(n)}).then(function(){return refreshState();});}
function showEditModal(n){var v=currentData[n];if(!v)return;document.getElementById("modalTitle").textContent="编辑: "+n;document.getElementById("editS").value=v.s||"unknown";document.getElementById("editT").value=v.t||"";document.getElementById("editR").value=v.r||"0,0";document.getElementById("editRs").value=v.rs||0;document.getElementById("editL").value=v.l||"";document.getElementById("editM").value=v.M||"";document.getElementById("editModal").classList.add("show");}
function closeEditModal(){document.getElementById("editModal").classList.remove("show");}
function saveEdit(){var n=document.getElementById("modalTitle").textContent.replace("编辑: ","");var b=JSON.stringify({s:document.getElementById("editS").value,t:document.getElementById("editT").value,r:document.getElementById("editR").value,rs:parseInt(document.getElementById("editRs").value)||0,l:document.getElementById("editL").value,M:document.getElementById("editM").value});fetch(PREFIX+"/list/edit/"+encodeURIComponent(n),{method:"POST",headers:{"Content-Type":"application/json"},body:b}).then(function(){closeEditModal();return refreshState();});}
function scheduleSync(){if(syncTimer)return;syncTimer=setTimeout(function(){syncTimer=null;refreshState();},100);}
function connectEvents(){
    if(cameraEvents)cameraEvents.close();
    cameraEvents=new EventSource(PREFIX+"/events");
    cameraEvents.addEventListener("change",scheduleSync);
}
renderList();
refreshState();
connectEvents();
if(REFRESH)setTimeout(function(){location.reload()},3000);
</script>
</body>
</html>"""


@cycctv_bp.route("/list-all")
def list_all():
    return jsonify({"list": the_list.get_all()})


@cycctv_bp.route("/settings")
def get_settings():
    return jsonify(the_list.get_auto_update_settings())


@cycctv_bp.route("/events")
def events():
    try:
        after_revision = int(request.headers.get("Last-Event-ID", "0"))
    except ValueError:
        after_revision = 0

    @stream_with_context
    def generate():
        last_revision = max(after_revision, 0)
        while True:
            changes = the_list.wait_for_events(last_revision, timeout=15)
            if not changes:
                yield ": heartbeat\n\n"
                continue
            for change in changes:
                last_revision = change["revision"]
                yield (
                    f"id: {last_revision}\n"
                    "event: change\n"
                    f"data: {json.dumps(change, ensure_ascii=False)}\n\n"
                )

    return Response(generate(), mimetype="text/event-stream", headers={
        "Cache-Control": "no-cache",
        "X-Accel-Buffering": "no",
    })


@cycctv_bp.route("/list-mock")
def list_mock():
    return render_template_string(
        MANAGEMENT_HTML,
        theList=the_list.get_all(),
        refresh="",
    )


@cycctv_bp.route("/list-mock/<cip>")
def list_mock_filtered(cip):
    return render_template_string(
        MANAGEMENT_HTML,
        theList=the_list.get_filtered(cip),
        refresh="",
    )


@cycctv_bp.route("/list/add", methods=["POST"])
def add_item():
    name = request.form.get("name", "").strip()
    if name:
        if the_list.add(name):
            save_list("add", [name])
    return jsonify(the_list.to_json())


@cycctv_bp.route("/list/remove/<name>")
def remove_item(name):
    the_list.remove(name)
    save_list("remove", [name])
    return jsonify(the_list.to_json())


@cycctv_bp.route("/list/setStatus/<name>/<status>")
def set_status(name, status):
    the_list.set_status(name, status)
    save_list("status", [name])
    return jsonify(the_list.to_json())


@cycctv_bp.route("/list/setTimeNow/<name>")
def set_time_now(name):
    the_list.set_time_now(name)
    save_list("timestamp", [name])
    return jsonify(the_list.to_json())


@cycctv_bp.route("/list/setTimeHourAgo/<name>")
def set_time_hour_ago(name):
    the_list.set_time_hour_ago(name)
    save_list("timestamp", [name])
    return jsonify(the_list.to_json())


@cycctv_bp.route("/list/edit/<name>", methods=["POST"])
def edit_item(name):
    data = request.get_json(force=True, silent=True) or {}
    the_list.update_item(name, data)
    save_list("edit", [name])
    return jsonify(the_list.to_json())


@cycctv_bp.route("/list/set-auto-update/<name>/<enabled>", methods=["POST"])
def set_auto_update(name, enabled):
    if enabled not in ("0", "1"):
        return jsonify({"status": "error", "message": "enabled must be 0 or 1"}), 400
    if not the_list.set_auto_update(name, enabled == "1"):
        return jsonify({"status": "error", "message": "条目不存在"}), 404
    save_list("auto_update", [name])
    return jsonify(the_list.get_auto_update_settings())
