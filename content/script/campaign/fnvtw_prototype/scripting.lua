-- 沿用原版战役引导顺序，只加载样板自己的入口。
load_script_libraries();
campaign_name = get_folder_name_and_shortform();
cm:set_campaign_name(campaign_name);

if campaign_name ~= "fnvtw_prototype" then
    return;
end;

package.path = package.path .. ";data/script/campaign/?.lua";
force_require("wh_campaign_setup");

cm:add_first_tick_callback(function()
    out("FNVTW: prototype first tick reached");
end);
