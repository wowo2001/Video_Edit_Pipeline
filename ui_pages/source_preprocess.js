const $ = id => document.getElementById(id);
const token = new URLSearchParams(location.search).get('token');
const url = (path, params = {}) => path + '?' + new URLSearchParams({token, ...params});
const canvas = $('canvas'), ctx = canvas.getContext('2d');
const portrait = $('portrait'), portraitCtx = portrait.getContext('2d');
let meta, profile, image, mode = 'blur', selected = null, drag = null, request = 0, timer;
let undoStack = [], redoStack = [], draftKey;
let revision = 0, finished = false;
let captionDrag = null;
let captionEdit = null;
const defaultCaption = {x: 70, y: 1220, width: 940, font_size: 64, max_lines: 2};
const defaultOverlay = {title: {y:400, font_size:80}, subtitle: {y:1470, font_size:80}, popup: {y:750, font_size:42}};
function overlayLayout() {
    if (!profile.overlay_layout) profile.overlay_layout = clone(defaultOverlay);
    return profile.overlay_layout;
}
const clone = value => JSON.parse(JSON.stringify(value));

function stamp(t) {
    return [Math.floor(t / 3600), Math.floor(t / 60 % 60), Math.floor(t % 60)]
        .map(n => n.toString().padStart(2, '0')).join(':');
}

async function api(path, body) {
    const response = await fetch(url(path), {method: 'POST',
        headers: {'Content-Type': 'application/json'}, body: JSON.stringify(body)});
    const data = await response.json();
    if (!response.ok) throw Error(data.error || '操作失败');
    return data;
}

function keepDraft() {
    if (!draftKey || finished) return;
    try {
        sessionStorage.setItem(draftKey, JSON.stringify({profile, undoStack, redoStack,
            time: Number($('time').value)}));
    } catch (_) { /* Storage is optional; editing works with browser storage disabled. */ }
}

function finishChange(before) {
    if (JSON.stringify(before) !== JSON.stringify(profile)) {
        invalidatePreview();
        undoStack.push(before);
        if (undoStack.length > 100) undoStack.shift();
        redoStack = [];
        $('status').textContent = '选区已修改，尚未保存。可撤销或继续调整。';
    }
    keepDraft();
    info();
    draw();
}

function invalidatePreview() {
    revision++;
    $('result').pause();
    $('result').hidden = true;
}

function change(action) {
    const before = clone(profile);
    action();
    finishChange(before);
}

function undo() {
    if (drag || captionDrag) return cancelDrag();
    if (!undoStack.length) return;
    redoStack.push(clone(profile));
    profile = undoStack.pop();
    invalidatePreview();
    selected = null;
    mode = 'blur';
    $('status').textContent = '已撤销上一步，可点击重做恢复。';
    keepDraft(); info(); draw();
}

function redo() {
    if (drag || captionDrag || !redoStack.length) return;
    undoStack.push(clone(profile));
    profile = redoStack.pop();
    invalidatePreview();
    selected = null;
    mode = 'blur';
    $('status').textContent = '已重做。';
    keepDraft(); info(); draw();
}

function cancelDrag() {
    if (captionDrag) {
        profile = captionDrag.before;
        captionDrag = null;
        $('status').textContent = '已取消本次字幕移动。';
        info(); draw(); return;
    }
    if (!drag) return;
    profile = drag.before;
    drag = null;
    $('status').textContent = '已取消本次拖动。';
    info(); draw();
}

function boxDraw(box, color, label) {
    ctx.strokeStyle = color;
    ctx.lineWidth = 3;
    ctx.strokeRect(box.x * canvas.width, box.y * canvas.height,
        box.width * canvas.width, box.height * canvas.height);
    ctx.fillStyle = color;
    ctx.font = '18px sans-serif';
    ctx.fillText(label, box.x * canvas.width + 5, Math.max(22, box.y * canvas.height + 22));
}

function drawPortrait() {
    const c = profile.crop, width = image.naturalWidth, height = image.naturalHeight;
    const sourceWidth = c.width * width, sourceHeight = c.height * height;
    const visibleHeight = Math.min(sourceHeight, sourceWidth * 1920 / 1080);
    const drawHeight = visibleHeight * 1080 / sourceWidth;
    const picture = context => context.drawImage(image,
        c.x * width, c.y * height + (sourceHeight - visibleHeight) / 2,
        sourceWidth, visibleHeight, 0, (1920 - drawHeight) / 2, 1080, drawHeight);
    const scale = 1080 / (c.width * width);
    const displayHeight = c.height * height * scale;
    const top = (1920 - displayHeight) / 2;
    portraitCtx.fillStyle = 'black';
    portraitCtx.fillRect(0, 0, 1080, 1920);
    picture(portraitCtx);
    for (const b of profile.blur_regions) {
        const x = (b.x - c.x) * width * scale;
        const y = top + (b.y - c.y) * height * scale;
        const w = b.width * width * scale, h = b.height * height * scale;
        portraitCtx.save();
        portraitCtx.beginPath();
        portraitCtx.rect(x, y, w, h);
        portraitCtx.clip();
        portraitCtx.filter = 'blur(14px)';
        picture(portraitCtx);
        portraitCtx.filter = 'none';
        // Clip the tint to the actual picture, leaving title bands black.
        portraitCtx.fillStyle = '#00000026';
        portraitCtx.fillRect(0, Math.max(0, top), 1080, Math.min(1920, displayHeight));
        portraitCtx.restore();
    }
    portraitCtx.save();
    portraitCtx.textAlign = 'center';
    portraitCtx.textBaseline = 'top';
    for (const [key, text] of [['title', meta.drama_title || profile.drama_title], ['subtitle', '副标题预览'], ['popup', '这一步，他到底想干什么？']]) {
        const layout = overlayLayout()[key];
        portraitCtx.font = `${layout.font_size}px CaptionPreview`;
        portraitCtx.fillStyle = key === 'popup' ? 'white' : '#FFCC00';
        if (key === 'popup') {
            portraitCtx.strokeStyle = 'black'; portraitCtx.lineWidth = 6;
            portraitCtx.strokeText(text, 540, layout.y);
        }
        portraitCtx.fillText(text, 540, layout.y);
    }
    portraitCtx.restore();
    drawCaption();
}

function captionHeight(layout) {
    return Math.ceil(layout.font_size * 1.3) * layout.max_lines + 16;
}

function captionLayout() {
    if (!profile.caption_layout) profile.caption_layout = {...defaultCaption};
    return profile.caption_layout;
}

function clampCaption(layout) {
    layout.font_size = Math.max(24, Math.min(96, Math.round(layout.font_size)));
    layout.max_lines = Math.max(1, Math.min(4, Math.round(layout.max_lines)));
    layout.width = Math.max(160, Math.min(1080, Math.round(layout.width)));
    layout.x = Math.max(0, Math.min(1080 - layout.width, Math.round(layout.x)));
    layout.y = Math.max(0, Math.min(1920 - captionHeight(layout), Math.round(layout.y)));
}

function drawCaption() {
    const layout = captionLayout(), h = captionHeight(layout);
    portraitCtx.save();
    portraitCtx.strokeStyle = '#68c7ff';
    portraitCtx.lineWidth = 5;
    portraitCtx.setLineDash([16, 10]);
    portraitCtx.strokeRect(layout.x, layout.y, layout.width, h);
    portraitCtx.setLineDash([]);
    portraitCtx.fillStyle = '#68c7ff';
    portraitCtx.fillRect(layout.x + layout.width - 14, layout.y + h - 14, 28, 28);
    portraitCtx.font = `${layout.font_size}px CaptionPreview`;
    portraitCtx.textAlign = 'center';
    portraitCtx.textBaseline = 'top';
    portraitCtx.lineJoin = 'round';
    const lines = [];
    for (const paragraph of $('captionSample').value.split('\n')) {
        let line = '';
        for (const character of paragraph) {
            if (line && portraitCtx.measureText(line + character).width > layout.width - 16) {
                lines.push(line); line = '';
            }
            line += character;
        }
        lines.push(line);
    }
    lines.slice(0, layout.max_lines).forEach((line, index) => {
        const x = layout.x + layout.width / 2;
        const y = layout.y + 8 + index * Math.ceil(layout.font_size * 1.3);
        portraitCtx.lineWidth = 6;
        portraitCtx.strokeStyle = 'black';
        portraitCtx.strokeText(line, x, y);
        portraitCtx.fillStyle = '#FFCC00';
        portraitCtx.fillText(line, x, y);
    });
    portraitCtx.restore();
}

function draw() {
    if (!image || !profile) return;
    ctx.clearRect(0, 0, canvas.width, canvas.height);
    ctx.drawImage(image, 0, 0, canvas.width, canvas.height);
    const c = profile.crop;
    ctx.fillStyle = '#0009';
    ctx.fillRect(0, 0, canvas.width, c.y * canvas.height);
    ctx.fillRect(0, (c.y + c.height) * canvas.height, canvas.width, (1 - c.y - c.height) * canvas.height);
    ctx.fillRect(0, c.y * canvas.height, c.x * canvas.width, c.height * canvas.height);
    ctx.fillRect((c.x + c.width) * canvas.width, c.y * canvas.height,
        (1 - c.x - c.width) * canvas.width, c.height * canvas.height);
    boxDraw(c, '#6fe8ba', '保留画面');
    profile.blur_regions.forEach((box, i) => {
        ctx.fillStyle = '#ffae4526';
        ctx.fillRect(box.x * canvas.width, box.y * canvas.height,
            box.width * canvas.width, box.height * canvas.height);
        boxDraw(box, '#ffb367', '模糊 ' + (i + 1));
    });
    const b = selected === 'crop' ? c : profile.blur_regions[selected];
    if (b) {
        ctx.fillStyle = 'white';
        ctx.fillRect((b.x + b.width) * canvas.width - 7,
            (b.y + b.height) * canvas.height - 7, 14, 14);
    }
    drawPortrait();
}

function deleteRegion(index) {
    if (!Number.isInteger(index)) return;
    change(() => {
        profile.blur_regions.splice(index, 1);
        selected = null;
        mode = 'blur';
    });
}

function info() {
    const c = profile.crop, width = meta.info.width, height = meta.info.height;
    const pictureHeight = Math.round(1080 * c.height * height / (c.width * width));
    $('cropInfo').textContent = `竖屏输出 1080 × 1920；画面宽度自动铺满 1080。`
        + (pictureHeight <= 1920 ? `画面高度约 ${pictureHeight}，上下留黑。` : '超出屏幕的上下部分会居中裁掉。');
    $('regions').replaceChildren();
    profile.blur_regions.forEach((box, index) => {
        const row = document.createElement('div');
        row.className = 'item' + (selected === index ? ' chosen' : '');
        const text = document.createElement('button');
        text.textContent = `区域 ${index + 1} · ${Math.round(box.width * width)} × ${Math.round(box.height * height)}`;
        text.onclick = () => { selected = index; mode = 'hand'; info(); draw(); };
        const remove = document.createElement('button');
        remove.textContent = '删除';
        remove.setAttribute('aria-label', '删除区域 ' + (index + 1));
        remove.onclick = () => deleteRegion(index);
        row.append(text, remove);
        $('regions').append(row);
    });
    if (!profile.blur_regions.length) $('regions').textContent = '未设置模糊区域（将跳过模糊）';
    $('blurMode').classList.toggle('active', mode === 'blur');
    $('cropMode').classList.toggle('active', mode === 'crop');
    $('handMode').classList.toggle('active', mode === 'hand');
    $('subtitleMode').classList.toggle('active', mode === 'subtitle');
    canvas.classList.toggle('hand-mode', mode === 'hand');
    canvas.classList.toggle('dragging', Boolean(drag));
    portrait.classList.toggle('dragging', Boolean(captionDrag));
    document.querySelector('.editing-views').classList.toggle('caption-edit', mode === 'subtitle');
    $('undo').disabled = !undoStack.length && !drag && !captionDrag;
    $('redo').disabled = !redoStack.length || Boolean(drag || captionDrag);
    $('crf').value = profile.crf;
    $('preset').value = profile.preset;
    for (const key of ['title', 'subtitle', 'popup']) {
        const box = overlayLayout()[key];
        for (const field of ['y', 'font_size']) {
            const input = $(`${key}_${field}`);
            if (document.activeElement !== input) input.value = box[field];
        }
        $(`${key}_y`).max = 1920-box.font_size;
    }
    const layout = captionLayout();
    for (const [id, key] of [['captionX','x'], ['captionY','y'], ['captionWidth','width'],
                            ['captionSize','font_size'], ['captionLines','max_lines']])
        if (document.activeElement !== $(id)) $(id).value = layout[key];
    $('captionX').max = 1080 - layout.width;
    $('captionY').max = 1920 - captionHeight(layout);
}

async function seek(time) {
    time = Math.max(0, Math.min(time, meta.info.duration - .05));
    $('seek').value = time;
    $('time').value = time.toFixed(3);
    const number = ++request;
    $('loading').hidden = false;
    $('loading').textContent = '正在截帧…';
    const frame = new Image();
    frame.onload = () => {
        if (number !== request) return;
        image = frame;
        canvas.width = frame.naturalWidth;
        canvas.height = frame.naturalHeight;
        $('loading').hidden = true;
        keepDraft(); draw();
    };
    frame.onerror = () => {
        if (number === request) $('loading').textContent = '截帧失败，请选择其他时间点';
    };
    frame.src = url('/frame', {t: time});
}

function point(event) {
    const rect = canvas.getBoundingClientRect();
    return {x: Math.max(0, Math.min(1, (event.clientX - rect.left) / rect.width)),
        y: Math.max(0, Math.min(1, (event.clientY - rect.top) / rect.height))};
}

canvas.onpointerdown = event => {
    if (!profile || event.button !== 0) return;
    const p = point(event), before = clone(profile);
    if (mode === 'hand') {
        // Hit-test the topmost blur first, then the retained-picture crop.
        const current = selected === 'crop' ? profile.crop : profile.blur_regions[selected];
        const onHandle = current && Math.abs(p.x - current.x - current.width) < .025
            && Math.abs(p.y - current.y - current.height) < .035;
        const inside = b => p.x >= b.x && p.x <= b.x + b.width && p.y >= b.y && p.y <= b.y + b.height;
        const hit = profile.blur_regions.map((box, i) => ({box, i})).reverse().find(v => inside(v.box));
        if (!onHandle) selected = hit ? hit.i : inside(profile.crop) ? 'crop' : null;
    }
    const box = selected === 'crop' ? profile.crop : profile.blur_regions[selected];
    canvas.setPointerCapture(event.pointerId);
    if (box && (mode === 'edit' || mode === 'hand')) {
        const handle = Math.abs(p.x - box.x - box.width) < .025
            && Math.abs(p.y - box.y - box.height) < .035;
        if (handle) drag = {kind: 'resize', start: p, original: {...box}, before};
        else if (p.x >= box.x && p.x <= box.x + box.width && p.y >= box.y && p.y <= box.y + box.height)
            drag = {kind: 'move', start: p, original: {...box}, before};
        // An unrelated click does not silently add another blur region.
        else { selected = null; info(); draw(); return; }
    } else if (mode === 'blur' || mode === 'crop') {
        drag = {kind: 'new', start: p, box: null, before};
        selected = null;
    }
    info();
};

canvas.onpointermove = event => {
    if (!drag) return;
    const p = point(event), d = drag;
    if (d.kind === 'new') {
        d.box = {x: Math.min(p.x, d.start.x), y: Math.min(p.y, d.start.y),
            width: Math.abs(p.x - d.start.x), height: Math.abs(p.y - d.start.y)};
        draw();
        boxDraw(d.box, mode === 'crop' ? '#6fe8ba' : '#ffb367', '新选区');
        // Show a new crop immediately in the portrait pane without committing it.
        if (mode === 'crop' && d.box.width > .003 && d.box.height > .003) {
            const original = profile.crop;
            profile.crop = d.box; drawPortrait(); profile.crop = original;
        }
        return;
    }
    const original = d.original;
    let box = d.kind === 'move'
        ? {...original, x: Math.max(0, Math.min(1 - original.width, original.x + p.x - d.start.x)),
            y: Math.max(0, Math.min(1 - original.height, original.y + p.y - d.start.y))}
        : {...original, width: Math.max(.005, p.x - original.x), height: Math.max(.005, p.y - original.y)};
    box.width = Math.min(box.width, 1 - box.x);
    box.height = Math.min(box.height, 1 - box.y);
    if (selected === 'crop') profile.crop = box;
    else profile.blur_regions[selected] = box;
    info(); draw();
};

canvas.onpointerup = () => {
    if (!drag) return;
    const {before, kind, box} = drag;
    if (kind === 'new' && box && box.width * meta.info.width >= 4 && box.height * meta.info.height >= 4) {
        if (mode === 'crop') { profile.crop = box; selected = 'crop'; mode = 'hand'; }
        else if (profile.blur_regions.length < 20) {
            profile.blur_regions.push(box);
            selected = profile.blur_regions.length - 1;
            mode = 'hand';
        }
    }
    drag = null;
    finishChange(before);
};
canvas.onpointercancel = cancelDrag;

$('undo').onclick = undo;
$('redo').onclick = redo;
$('handMode').onclick = () => { mode = 'hand'; info(); draw(); };
$('subtitleMode').onclick = () => { mode = mode === 'subtitle' ? 'hand' : 'subtitle'; info(); draw(); };
$('blurMode').onclick = () => { mode = 'blur'; selected = null; info(); draw(); };
$('cropMode').onclick = () => { mode = 'crop'; selected = null; info(); draw(); };
function crop(ratio) {
    change(() => {
        const aspect = meta.info.width / meta.info.height;
        const width = ratio ? Math.min(1, ratio / aspect) : 1;
        const height = ratio ? Math.min(1, aspect / ratio) : 1;
        profile.crop = {x: (1 - width) / 2, y: (1 - height) / 2, width, height};
        selected = 'crop'; mode = 'hand';
    });
}
$('crop43').onclick = () => crop(4 / 3);
$('crop916').onclick = () => crop(9 / 16);
$('crop169').onclick = () => crop(16 / 9);
$('full').onclick = () => crop(null);
$('skip').onclick = () => change(() => { profile.blur_regions = []; selected = null; mode = 'blur'; });
$('crf').onchange = () => change(() => { profile.crf = Number($('crf').value); });
$('preset').onchange = () => change(() => { profile.preset = $('preset').value; });
for (const key of ['title', 'subtitle', 'popup']) {
    for (const field of ['y', 'font_size']) {
        const input = $(`${key}_${field}`);
        input.oninput = () => {
            const value = Number(input.value);
            if (input.value === '' || !Number.isInteger(value) || value < Number(input.min) || value > Number(input.max)) return;
            change(() => {
                const box = overlayLayout()[key];
                box[field] = value;
                box.y = Math.min(box.y, 1920-box.font_size);
            });
        };
        input.onblur = () => { input.value = overlayLayout()[key][field]; };
    }
}
for (const [id, key] of [['captionX','x'], ['captionY','y'], ['captionWidth','width'],
                        ['captionSize','font_size'], ['captionLines','max_lines']]) {
    const update = () => {
        if (!captionEdit || captionEdit.id !== id) {
            commitCaptionEdit();
            captionEdit = {id, key, before: clone(profile)};
        }
        const raw = $(id).value, value = Number(raw);
        // Allow partial typing (for example 6 -> 68 -> 680) without replacing it.
        if (raw === '' || !Number.isFinite(value) || value < Number($(id).min || 0)
            || ($(id).max !== '' && value > Number($(id).max))) return;
        captionLayout()[key] = value;
        clampCaption(captionLayout());
        invalidatePreview(); keepDraft(); info(); draw();
    };
    $(id).oninput = update;
    $(id).onchange = () => { update(); commitCaptionEdit(); };
    $(id).onblur = commitCaptionEdit;
}
function commitCaptionEdit() {
    if (!captionEdit) return;
    const edit = captionEdit; captionEdit = null;
    $(edit.id).value = captionLayout()[edit.key];
    finishChange(edit.before);
}
$('captionCenter').onclick = () => change(() => {
    const layout = captionLayout(); layout.x = Math.round((1080 - layout.width) / 2);
});
$('captionSample').oninput = () => { invalidatePreview(); draw(); };

function portraitPoint(event) {
    const rect = portrait.getBoundingClientRect();
    return {x: Math.max(0, Math.min(1080, (event.clientX - rect.left) / rect.width * 1080)),
        y: Math.max(0, Math.min(1920, (event.clientY - rect.top) / rect.height * 1920))};
}
portrait.onpointerdown = event => {
    if (!profile || event.button !== 0) return;
    const layout = captionLayout(), p = portraitPoint(event), h = captionHeight(layout);
    const handle = Math.abs(p.x - layout.x - layout.width) < 40 && Math.abs(p.y - layout.y - h) < 60;
    const inside = p.x >= layout.x && p.x <= layout.x + layout.width && p.y >= layout.y && p.y <= layout.y + h;
    if (!handle && !inside) return;
    portrait.setPointerCapture(event.pointerId);
    captionDrag = {before: clone(profile), original: {...layout}, start: p, resize: handle};
    info();
};
portrait.onpointermove = event => {
    if (!captionDrag) return;
    const p = portraitPoint(event), d = captionDrag, layout = captionLayout();
    if (d.resize) layout.width = d.original.width + p.x - d.start.x;
    else { layout.x = d.original.x + p.x - d.start.x; layout.y = d.original.y + p.y - d.start.y; }
    clampCaption(layout); info(); draw();
};
portrait.onpointerup = () => {
    if (!captionDrag) return;
    const before = captionDrag.before; captionDrag = null; finishChange(before);
};
portrait.onpointercancel = cancelDrag;
document.addEventListener('keydown', event => {
    if (event.key === 'Escape') { cancelDrag(); return; }
    if (['INPUT', 'SELECT', 'TEXTAREA'].includes(event.target.tagName)) return;
    if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 'z') {
        event.preventDefault(); event.shiftKey ? redo() : undo();
    } else if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 'y') {
        event.preventDefault(); redo();
    } else if (event.key === 'Delete' && Number.isInteger(selected)) {
        event.preventDefault(); deleteRegion(selected);
    }
});

$('seek').oninput = () => {
    clearTimeout(timer);
    const time = Number($('seek').value);
    $('time').value = time.toFixed(2);
    timer = setTimeout(() => seek(time), 180);
};
$('jump').onclick = () => seek(Number($('time').value));
const frameSeconds = () => 1 / meta.info.fps.split('/').reduce((a, b) => a / b);
$('backFrame').onclick = () => seek(Number($('time').value) - frameSeconds());
$('nextFrame').onclick = () => seek(Number($('time').value) + frameSeconds());
$('preview').onclick = async () => {
    const previewRevision = revision;
    $('preview').disabled = true;
    $('status').textContent = '正在生成 3 秒实际竖屏预览…';
    try {
        await api('/api/preview', {...profile, caption_sample: $('captionSample').value, time: Number($('time').value)});
        if (previewRevision !== revision) {
            $('status').textContent = '选区已改变，请重新生成竖屏预览。';
            return;
        }
        $('result').src = url('/preview.mp4', {v: Date.now()});
        $('result').hidden = false;
        $('result').load();
        $('status').textContent = '竖屏预览已生成。确认后点击保存。';
    } catch (error) { $('status').textContent = error.message; }
    finally { $('preview').disabled = false; }
};
$('save').onclick = async () => {
    $('save').disabled = true;
    try {
        await api('/api/save', profile);
        finished = true;
        try { sessionStorage.removeItem(draftKey); } catch (_) {}
        $('editor').hidden = true;
        $('complete').style.display = 'block';
        if (meta.configure_only) $('doneText').textContent = '配置已保存。之后双击 run_main.bat 即可整批自动处理，本次没有启动生产或上传。';
    } catch (error) { $('status').textContent = error.message; $('save').disabled = false; }
};
$('cancel').onclick = async () => {
    await api('/api/cancel', {});
    finished = true;
    $('editor').hidden = true;
    $('doneTitle').textContent = '本次处理已取消';
    $('doneText').textContent = '没有启动整批任务，可以关闭此页面。';
    $('complete').style.display = 'block';
};

async function init() {
    meta = await (await fetch(url('/api/meta'))).json();
    profile = meta.profile;
    captionLayout();
    draftKey = 'source-selection:' + meta.profile_path;
    let time = Math.min(meta.initial_time ?? 60, meta.info.duration - .05);
    try {
        const draft = JSON.parse(sessionStorage.getItem(draftKey));
        if (draft && JSON.stringify(draft.profile.reference) === JSON.stringify(profile.reference)) {
            profile = draft.profile;
            captionLayout();
            undoStack = draft.undoStack || [];
            redoStack = draft.redoStack || [];
            time = draft.time;
            $('status').textContent = '已恢复本页未保存的选区和撤销记录。';
        }
    } catch (_) {}
    $('summary').textContent = `${meta.title} · 本批 ${meta.batch_count} 集 · 参考素材 ${meta.info.width} × ${meta.info.height} · 选区将应用于所有集数`;
    $('seek').max = Math.max(0, meta.info.duration - .05);
    $('duration').textContent = '/ ' + stamp(meta.info.duration);
    if (meta.configure_only) {
        $('save').textContent = '保存整批配置（本次不运行）';
        if (!undoStack.length) $('status').textContent = '尚未保存。本页只修改配置，保存后不会制作或上传。';
    }
    info();
    await document.fonts.load('64px CaptionPreview');
    await seek(time);
    for (let i = 0; i < 16; i++) {
        const t = meta.info.duration * (i + .5) / 16;
        const button = document.createElement('button');
        button.className = 'thumb';
        const thumbnail = document.createElement('img');
        thumbnail.alt = stamp(t);
        const label = document.createElement('span');
        label.textContent = stamp(t);
        button.append(thumbnail, label);
        button.onclick = () => seek(t);
        $('thumbs').append(button);
        await new Promise(resolve => {
            thumbnail.onload = thumbnail.onerror = resolve;
            thumbnail.src = url('/frame', {t, thumb: 1});
        });
    }
}
init().catch(error => { $('status').textContent = error.message; });
