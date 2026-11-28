/* The real Python catalog is supplied on stdin. No supplier calls or DOM shim. */
'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const root = path.resolve(__dirname, '../..');
const profiles = JSON.parse(fs.readFileSync(0, 'utf8'));
const provider = {builtin_model_video_profiles: profiles};
const context = {window:{}, document:{querySelectorAll:()=>[]},
    fetch:async()=>({ok:true,json:async()=>({favorites:[],view:'all'})})};
vm.runInNewContext(fs.readFileSync(root+'/static/js/model-picker.js','utf8'), context);
const picker = context.window.CanvasModelPicker;
const base = {duration:4,aspect_ratio:'16:9',resolution:'',images:[],videos:[],audios:[]};
const error = (model, changes={}) => picker.videoError(picker.videoProfileFor(provider,model,changes.video_channel), {...base,...changes});
assert(error('doubao-seedance-2.0-mini',{duration:3}));
assert.equal(error('doubao-seedance-2.0-mini'), '');
assert(error('doubao-seedance-2.0-mini',{resolution:'1080p'}));
assert(error('doubao-seedance-2.5',{images:[{role:'last_frame'}]}));
assert(error('doubao-seedance-2.5',{images:[{},{}]}));
assert.equal(error('doubao-seedance-2.5',{images:[{},{}],multimodal:true}), '');
assert.match(picker.videoInputNote(profiles['doubao-seedance-2.5'],{resolution:'1080p'}),/另计费用/);
assert(error('grok-imagine-video',{duration:15,multimodal:true}));
assert(error('grok-imagine-video-1.5',{resolution:'1080p',images:[{},{}]}));
assert(error('grok-1.5-video-6s',{duration:6}));
assert.equal(error('grok-1.5-video-6s',{duration:6,images:[{}]}), '');
assert(error('sora-2'));
assert.equal(error('sora-2',{video_channel:'official'}), '');
assert(error('sora-2',{video_channel:'official',duration:15}));
assert.equal(error('sora-2',{video_channel:'compatible',duration:15}), '');
assert(error('veo3.1',{duration:5}));
assert.equal(error('veo3.1',{duration:8}), '');
assert(error('veo3.1',{duration:8,resolution:'1080p'}));
assert(error('viduq2-pro',{aspect_ratio:'adaptive',images:[{},{}]}));
assert.equal(error('viduq2-pro',{aspect_ratio:'adaptive',images:[{},{}],multimodal:true}), '');
assert(error('not-adapted'));
assert.equal(picker.videoError({}, {...base,duration:60}), '', 'other suppliers retain their own contract');
const saved = {videoDuration:3,videoModel:'doubao-seedance-2.0-mini',videoAspect:'21:9',videoResolution:'1080p'};
const before = JSON.stringify(saved);
picker.videoError(profiles[saved.videoModel],picker.videoParameters(saved));
assert.equal(JSON.stringify(saved), before, 'opening saved settings never rewrites invalid values');

// Check actual smart controls with the same catalog, including saved invalid options.
const smart = vm.createContext({settings:{engine:'api',apiKind:'video',videoModel:'doubao-seedance-2.0-mini',videoDuration:3},
    window:context.window,apiProviderById:()=>provider,escapeHtml:String,tr:key=>key,videoAspectIconClass:()=>''});
const source = fs.readFileSync(root+'/static/js/smart-canvas.js','utf8');
for(const name of ['normalizeSmartVideoModeSettings','currentVideoProfile','renderVideoDurationControl','renderVideoAspectControl','renderVideoResolutionControl','renderVideoModelControl','renderVideoToggleControl','renderVideoTrustedAssetControl']){
    const start=source.indexOf('function '+name+'(');
    vm.runInContext(source.slice(start,source.indexOf('\n}',start)+2),smart);
}
const duration=smart.renderVideoDurationControl();
assert(duration.includes('>3s</span>'), 'saved invalid duration remains visible');
assert(!duration.includes('data-smart-value="3"') && !duration.includes('<input'));
for(const time of [4,10,15]) assert(duration.includes(`data-smart-value="${time}"`));
smart.settings.videoModel='veo3.1';smart.settings.videoAspect='21:9';smart.settings.videoResolution='1080p';
assert.match(smart.renderVideoAspectControl(), /disabled[^>]*data-smart-value="21:9"/);
assert.match(smart.renderVideoResolutionControl(), /disabled[^>]*data-smart-value="1080p"/);
assert.match(smart.renderVideoModelControl(['not-adapted']), /disabled[^>]*data-smart-value="not-adapted"/);
smart.settings.videoModel='doubao-seedance-2.5';smart.settings.videoResolution='720P';
assert(!smart.renderVideoResolutionControl().includes('不支持'));
assert.equal(picker.videoChoices(['480p','720p'],'720P',true).length,2);
const automatic={engine:'api',videoModel:'veo3.1',videoMultimodal:true};
smart.normalizeSmartVideoModeSettings(automatic,true);
assert.equal(automatic.videoMultimodal,false,'legacy default cannot enable an unsupported mode');
const explicit={...automatic,videoMultimodal:true,_videoMultimodalUserSet:true};
smart.normalizeSmartVideoModeSettings(explicit,true);
assert.equal(explicit.videoMultimodal,true,'stored options are preserved');
assert.equal(picker.videoError(profiles['veo3.1'],picker.videoParameters({...explicit,videoDuration:8},profiles['veo3.1'])), '');
const oldFlags={videoDuration:4,videoAspect:'16:9',videoCameraFixed:true,videoWatermark:true,
    videoUseFrameRoles:true,videoMultimodal:true,videoTrustedAsset:true};
const flagsBefore=JSON.stringify(oldFlags), grokProfile=profiles['grok-imagine-video-1.5'];
assert.equal(picker.videoError(grokProfile,picker.videoParameters(oldFlags,grokProfile)), '');
assert.equal(JSON.stringify(oldFlags),flagsBefore,'filtering does not overwrite saved options');
smart.settings={engine:'api',apiKind:'video',videoModel:'grok-imagine-video-1.5',...oldFlags};
for(const key of ['videoEnhancePrompt','videoEnableUpsample','videoGenerateAudio','videoCameraFixed',
    'videoWatermark','videoMultimodal','videoUseFrameRoles','videoTrustedAsset']){
    assert.equal(smart.renderVideoToggleControl(key,key),'','unsupported switch is absent, even when saved as on');
}
assert.equal(smart.renderVideoTrustedAssetControl(),'','hidden trusted mode must not leave source controls');
smart.settings.videoModel='doubao-seedance-2.5';
assert(smart.renderVideoToggleControl('videoCameraFixed','fixed').includes('data-toggle-param="videoCameraFixed"'));
smart.settings.videoModel='sora-2';smart.settings.videoChannel='official';
assert.equal(smart.renderVideoToggleControl('videoWatermark','watermark'),'');
smart.settings.videoChannel='compatible';
assert(smart.renderVideoToggleControl('videoWatermark','watermark').includes('data-toggle-param="videoWatermark"'));
console.log('Video catalog, saved values, channel variants and actual smart controls passed.');
