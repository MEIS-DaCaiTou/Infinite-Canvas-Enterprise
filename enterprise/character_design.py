"""Bounded character editing metadata; media authorization stays in Characters."""
from enterprise.character_repository import CharacterError

ASSET_KINDS = {'full_body', 'portrait', 'expression', 'turnaround'}
NUMERIC_KEYS = {
    'smooth', 'beauty', 'texture', 'brightness', 'rosy', 'whiten', 'fleck',
    'eye_size', 'eye_bright', 'eye_distance', 'eye_angle', 'brow_height',
    'nose_size', 'nose_width', 'nose_height', 'lip_size', 'lip_width',
    'face_slim', 'chin', 'jaw', 'forehead', 'cheek',
    'chest', 'height', 'posture', 'legs', 'shoulder', 'head', 'slim',
    'belly', 'arms', 'hips', 'leg_slim', 'neck_left', 'neck_right',
    'waist', 'neck_length_left', 'neck_length_right', 'shoulder_width', 'body',
}
TEXT_KEYS = {'feature', 'hair', 'hair_color', 'makeup', 'lip_color', 'outfit', 'style'}


def design_profile(value):
    if (not isinstance(value, dict) or set(value) - {'version', 'values', 'notes', 'preview_source'}
            or type(value.get('version')) is not int or value['version'] != 1):
        raise CharacterError(400, '角色造型参数版本无效')
    values = value.get('values', {})
    if not isinstance(values, dict) or set(values) - NUMERIC_KEYS - TEXT_KEYS:
        raise CharacterError(400, '角色造型参数无效')
    for key, item in values.items():
        if key in NUMERIC_KEYS:
            if type(item) is not int or not -100 <= item <= 100:
                raise CharacterError(400, '角色造型数值应为-100至100的整数')
        elif not isinstance(item, str) or len(item) > 200:
            raise CharacterError(400, '角色造型选项过长')
    notes = value.get('notes', '')
    if not isinstance(notes, str) or len(notes) > 1000:
        raise CharacterError(400, '角色造型补充说明过长')
    result = {'version': 1, 'values': dict(values), 'notes': notes}
    if 'preview_source' in value:
        if not isinstance(value['preview_source'], str) or len(value['preview_source']) > 2000:
            raise CharacterError(400, '角色预览原图无效')
        result['preview_source'] = value['preview_source']
    return result


def voice_profile(value):
    allowed={'provider_id','model','voice','speed','input','instructions','url'}
    if not isinstance(value,dict) or set(value)-allowed:
        raise CharacterError(400,'角色音色字段无效')
    limits={'provider_id':200,'model':100,'voice':100,'input':2000,'instructions':1000,'url':2000}
    for key,maximum in limits.items():
        if not isinstance(value.get(key,''),str) or len(value.get(key,''))>maximum:
            raise CharacterError(400,'角色音色内容过长')
    speed=value.get('speed',1)
    if type(speed) not in (int,float) or not 0.25<=speed<=4:
        raise CharacterError(400,'角色语速无效')
    return {**value,'speed':speed}
