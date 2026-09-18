// =====================================================================
// 10_clear_start_creeps.j —— 开局清除出生点附近的野怪
//
// 行为：地图开始时，把每个【用户/电脑玩家】出生点周围 1200 码内的
//       中立敌对野怪（owner = PLAYER_NEUTRAL_AGGRESSIVE）整只删除。
//       玩家单位、中立被动（可占领的 gold mine / 建筑等）都不动。
//
// 说明：
//   - 1200 码 ≈ 2.875 个格子（1 格 = 128 码 = 96 WC3 单位显示距离）
//   - 用 0 秒延时计时器触发：等 main 的 RunInitializationTriggers 执行完、
//     游戏正式开始后再删，避免 melee 初始化阶段产生竞争
//   - 码(radius)用的是世界坐标：1 码 = 1.0，1200 码就是 1200.0
//   - 占位符 $CLEAR_RADIUS=1200 默认 1200；注入时用 --set-CLEAR-RADIUS 值 覆盖
//     （写成 $名字=默认值 的形式，没给 --set 也能直接用；不写默认值的话
//       add_triggers.py 会直接中止，免得把非法 Jass 写进地图）
// =====================================================================

function Trig_ClearStartCreeps_IsTarget takes unit u returns boolean
    local player p = GetOwningPlayer( u )
    // 只要中立敌对（野怪）。排除建筑防止误删出生点附近的中立建筑类野怪窝棚
    return p == Player(PLAYER_NEUTRAL_AGGRESSIVE) and not IsUnitType( u, UNIT_TYPE_STRUCTURE )
endfunction

function Trig_ClearStartCreeps_Loop takes nothing returns nothing
    local unit u = GetEnumUnit( )
    if Trig_ClearStartCreeps_IsTarget( u ) then
        call RemoveUnit( u )
    endif
    set u = null
endfunction

function Trig_ClearStartCreeps_Actions takes nothing returns nothing
    local integer pid = 0
    local integer nStart = 0
    local group g = CreateGroup( )
    local real x = 0
    local real y = 0
    local player p = null
    loop
        exitwhen pid >= GetPlayers( )
        set p = Player( pid )
        // 只处理真实玩家槽位（用户/电脑）；观察者没有出生点
        if GetPlayerController( p ) == MAP_CONTROL_USER or GetPlayerController( p ) == MAP_CONTROL_COMPUTER then
            set nStart = GetPlayerStartLocation( p )
            if nStart >= 0 then
                set x = GetStartLocationX( nStart )
                set y = GetStartLocationY( nStart )
                call GroupEnumUnitsInRange( g, x, y, $CLEAR_RADIUS=1200 + 0.0, null )
                call ForGroup( g, function Trig_ClearStartCreeps_Loop )
            endif
        endif
        set pid = pid + 1
    endloop
    call DestroyGroup( g )
    set g = null
    set p = null
endfunction

function InitTrig_ClearStartCreeps takes nothing returns nothing
    local trigger t = CreateTrigger( )
    // 0.01 秒后执行一次：开局删一波
    call TriggerRegisterTimerEvent( t, 0.01, false )
    call TriggerAddAction( t, function Trig_ClearStartCreeps_Actions )
endfunction
