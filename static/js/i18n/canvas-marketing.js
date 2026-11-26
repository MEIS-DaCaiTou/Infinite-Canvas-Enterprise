(function(){
    const words={
        entry:['智能多尺寸','Smart resize'],description:['批量生成适用于多个广告/电商平台的版本','Create sizes for ad and shopping platforms'],
        choose:['选择尺寸','Choose sizes'],add:['新增自定义尺寸','Add custom size'],edit:['编辑自定义尺寸','Edit custom size'],
        name:['尺寸名称','Size name'],nameHint:['请输入尺寸名称','Enter size name'],size:['尺寸','Size'],width:['宽度','Width'],height:['高度','Height'],
        lock:['锁定比例','Lock aspect ratio'],save:['保存','Save'],cancel:['取消','Cancel'],remove:['删除','Delete'],close:['关闭','Close'],
        model:['平台与模型','Provider and model'],settings:['生成设置','Generation settings'],generate:['生成','Generate'],submitting:['提交中…','Submitting…'],
        noModel:['尚未配置支持尺寸编辑的 Seedream 5.5 模型','Configure a Seedream 5.5 image editing model'],invalidSize:['请输入有效的整数宽高','Enter valid integer dimensions'],
        notAuthorized:['当前账号未获该平台渠道授权，请选择已授权渠道或联系管理员。','This account has no channel access. Choose an authorized provider or contact your administrator.'],
        checkingSource:['正在核对调用来源…','Checking call source…'],
        saveFailed:['尺寸未能保存，请保留当前内容并重试','Could not save this size. Keep your changes and retry'],
        main:['电商主图','Product main image'],portrait:['电商长图','Product portrait'],story:['竖屏视频封面','Portrait video cover'],
        video:['横屏视频封面','Landscape video cover'],poster:['横屏海报','Landscape poster'],cinema:['宽屏电影画幅','Cinema widescreen']
    };
    window.StudioI18n.register(Object.fromEntries(Object.entries(words).map(([key,[zh,en]])=>['multiSize.'+key,{zh,en}])));
})();
