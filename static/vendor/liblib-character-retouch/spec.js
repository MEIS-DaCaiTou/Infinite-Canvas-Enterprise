/* Parameter specification recovered from public module 725942. */
const values={}; const e={s:a=>{for(let i=0;i<a.length;i+=3)values[a[i]]=a[i+2];}};
      let t = [];
      function r(e, n, i = -100, o = 100, a = "list") {
        for (let r of n.trim().split("\n")) {
          let [n, l] = r.trim().split(" ");
          t.push({
            key: n,
            label: l,
            group: e,
            type: a,
            min: i,
            max: o,
            status: "approximate",
          });
        }
      }
      for (let e of (r(
        "脸型",
        `
ai_shrink_head 小脸
bottom_half_of_face 下庭
cheekbone 颧骨
cheekbone_left 左颧骨
cheekbone_right 右颧骨
face_forehead 额头
face_trans V脸
jaw_trans 下巴高度
mandible 下颌
mandible_left 左下颌
mandible_right 右下颌
middle_half_of_face 中庭
philtrum_warp 人中
narrow_face 脸部宽度
temple 太阳穴
temple_left 左太阳穴
temple_right 右太阳穴`,
      ),
      t))
        "ai_shrink_head" === e.key && (e.min = 0);
      for (let e of (r(
        "眼睛",
        `
eye_distance 眼距
eye_distance_left 左眼距
eye_distance_right 右眼距
eye_height 眼高
eye_height_left 左眼高
eye_height_right 右眼高
eye_lid_left 左眼睑
eye_lid_right 右眼睑
eye_tilt_left 左眼倾斜
eye_tilt_right 右眼倾斜
eye_trans 眼睛大小
eye_trans_left 左眼大小
eye_trans_right 右眼大小
eye_up_down_left 左眼上下
eye_up_down_right 右眼上下
eye_width 眼宽
eye_width_left 左眼宽
eye_width_right 右眼宽
inner_eye_corner_left 左开眼角
inner_eye_corner_right 右开眼角`,
      ),
      r(
        "眉毛",
        `
eyebrow_distance 眉间距
eyebrow_distance_left 左眉间距
eyebrow_distance_right 右眉间距
eyebrow_height 眉毛上下
eyebrow_height_left 左眉上下
eyebrow_height_right 右眉上下
eyebrow_ridge 眉峰
eyebrow_ridge_left 左眉峰
eyebrow_ridge_right 右眉峰
eyebrow_size 眉毛粗细
eyebrow_size_left 左眉粗细
eyebrow_size_right 右眉粗细
eyebrow_tilt 眉毛倾斜
eyebrow_tilt_left 左眉倾斜
eyebrow_tilt_right 右眉倾斜`,
      ),
      r(
        "鼻子",
        `
bridge_nose 鼻梁
nasal_root 山根
nasal_tip 鼻尖
nose_longer 鼻子长短
scale_nose 鼻子大小
shrink_nose 鼻翼`,
      ),
      r(
        "嘴巴",
        `
high_mouth 嘴巴上下
lowerlip_enhance 丰下唇
mouth_breadth 嘴巴宽度
mouth_high 丰唇
mouth_smile 嘴角调整
mouth_tilted 嘴巴倾斜
mouth_trans 嘴巴大小
upperlip_enhance 丰上唇`,
      ),
      r(
        "肤色",
        `
face_balance_alpha 质感磨皮
skin_hdr_alpha 皮肤透亮
skin_red_alpha 皮肤红润
skin_white_alpha 皮肤美白
sharpen_alpha 皮肤纹理
smooth_face_skin_alpha 高低频磨皮
smooth_face_skin_low_alpha 低频平整`,
        0,
      ),
      r(
        "肤色",
        `smooth_face_skin_hight_alpha 高频增强
skin_color_hue_alpha 肤色偏好`,
      ),
      r(
        "眼牙",
        `
bright_eye 亮眼
bright_eye_left 左眼亮眼
bright_eye_right 右眼亮眼
reduce_redness 祛红血丝
white_teeth 牙齿美白
white_teeth_luminance 牙齿明度
white_teeth_remove_yellow 牙齿祛黄`,
        0,
      ),
      r(
        "妆发",
        `
eyebrow_deepen 眉毛增强
eyeshadow_deepen 眼妆增强
facial_deepen 腮红增强
lipstick_deepen 唇妆增强
highlight_alpha 高光立体
shadow_light 阴影立体
black_hair 发色加深`,
        0,
      ),
      r("妆发", "fluffy_hair 颅顶高度"),
      r(
        "妆发",
        "mouth 唇彩\nblush 腮红\neye 美瞳\neyebrow 眉色\nhair_color 发色\neyeshadow 眼影",
        0,
        100,
        "makeup",
      ),
      r("调色", "exposure 曝光", -500, 500, "int"),
      r(
        "调色",
        "constrast 对比度\nsaturability 饱和度\ntemperature 色温\nhue 色调\nhighlight 高光\nshadow 阴影\nvignette_adjustment 暗角",
        -100,
        100,
        "int",
      ),
      r(
        "身材",
        `body_shape_chest_enlarge 丰胸
body_shape_slim 瘦身
body_shape_slim_hand 瘦手臂
body_shape_slim_hip 美臀
body_shape_thin_shoulders 肩膀宽度`,
      ),
      r(
        "身材",
        `body_shape_heighten 增高
body_shape_lengthen 长腿
body_shape_right_shoulder 直角肩
body_shape_shrink_head 小头
body_shape_slim_belly 瘦肚子
body_shape_slim_leg 瘦腿
body_shape_slim_waist 美腰`,
        0,
      ),
      `
body_shape_hunch_back 驼背
body_shape_slim_neck_left 左侧瘦脖
body_shape_slim_neck_right 右侧瘦脖
body_shape_swan_neck_left 左侧天鹅颈
body_shape_swan_neck_right 右侧天鹅颈
multibody_beauty 多人塑形
aegyosal_fill 卧蚕丰盈
angulus_oris_fill 嘴角丰盈
apple_cheek_fillers 苹果肌丰盈
beauty_belly_alpha 祛妊娠纹
double_chin 祛双下巴
face_restore_alpha 面部跑焦修复
flaw_clean_alpha 身体祛瑕疵
lip_remove_alpha 祛唇纹
makeup_protect 妆容保护
nevus_removal_flag 祛痣
remove_axillary_breast 祛副乳
remove_pouch 祛黑眼圈
shiny_clean_alpha 祛油光
fleck_clean_flag 祛斑祛痘
skin_fleck_clean_flag 身体祛斑祛痘
wrinkle_cheek_removal_alpha 祛面颊纹
wrinkle_forehead_removal_alpha 祛抬头纹
wrinkle_nasolabial_removal_alpha 祛法令纹
wrinkle_neck_removal_alpha 祛颈纹
wrinkle_periorbital_removal_alpha 祛眼周纹
body_symmetry 上半身对称
hairline_fill 发缝填充
broken_hair 祛碎发
broken_hair_background_area 背景祛碎发
broken_hair_hair_area 人像祛碎发
brow_arch_fill 眉弓丰盈
chin_fillers 下巴丰盈
eye_socket_fillers 眼窝丰盈
fore_head_fillers 额头丰盈
nose_fillers 鼻基底丰盈
tear_trough 泪沟丰盈
jowl_fill 面颊丰盈
fore_head_smooth 额头平整
perioral_smooth 口周平整
periorbital_smooth 眼周平整
facial_contour 脸部轮廓流畅
run_symmetry_list 对称性液化
face_symmetry 五官对称
threed_left_right 3D左右塑颜
threed_up_down 3D上下塑颜
malars_smooth 面中平整
neutral_gray_enhance_alpha 中性灰立体
neutral_gray_smooth_alpha 中性灰平整
reduce_glass_light 眼镜祛反光
face_beauty_alpha AI美颜
skin_color_lut_alpha 肤色LUT程度
skin_color_lut_path 肤色LUT素材
skin_tone_body_alpha 身体肤色统一
skin_tone_face_alpha 脸部肤色统一
skin_tone_multiple_alpha 多人肤色统一
smooth_not_face_skin_alpha 身体高低频
smooth_not_face_skin_hight_alpha 身体高频增强
smooth_not_face_skin_low_alpha 身体低频平整
teeth_beauty 牙齿修复
teeth_clean_alpha 牙齿祛瑕疵
smooth_hair 头发柔顺
makeup_highlight 高光素材
eyeliner 眼线素材
facialdecals 妆饰素材
feature 修容素材
eyelash 睫毛素材
eyesocket 卧蚕素材
eye_light_type_id 眼神光素材
eye_light_alpha_left 左眼神光程度
eye_light_alpha_right 右眼神光程度
eye_light_h_flip_left 左眼神光翻转
eye_light_h_flip_right 右眼神光翻转
eye_light_rotate_left 左眼神光旋转
eye_light_rotate_right 右眼神光旋转
eye_light_size_left 左眼神光缩放
eye_light_size_right 右眼神光缩放
eye_light_x_pos_left 左眼神光水平位置
eye_light_x_pos_right 右眼神光水平位置
eye_light_y_pos_left 左眼神光垂直位置
eye_light_y_pos_right 右眼神光垂直位置`
        .trim()
        .split("\n"))) {
        let [r, n] = e.split(" ");
        t.push({
          key: r,
          label: n,
          group: "未支持",
          type: "list",
          min: 0,
          max: 100,
          status: "unsupported",
          reason:
            "缺少对应的生成式模型、身体模型或美图专有素材；不以普通滤镜冒充此功能。",
        });
      }
      let n = Object.fromEntries(t.map((e) => [e.key, e])),
        i = new Set(
          t
            .filter(
              (e) =>
                ["脸型", "眼睛", "眉毛", "鼻子", "嘴巴"].includes(e.group) ||
                "fluffy_hair" === e.key,
            )
            .map((e) => e.key),
        ),
        o = new Set(t.filter((e) => "身材" === e.group).map((e) => e.key));
      e.s(["y", 0, o, "j", 0, t, "G", 0, n, "w", 0, i]);
export const {G,j,w,y}=values;
