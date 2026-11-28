#==============================================================================
# ■ TianJiangBattleResidueFix
#------------------------------------------------------------------------------
# 战斗中残留文字修复
#
# 【症状】
#   战斗里点过"物品"（使用 / 投掷）之后，物品清单与帮助文字会留在画面上，
#   战斗结束回到地图后仍然盖在画面上不消失（地图上能看到半透明的物品名、
#   数量、"价格 x 范围 xx"）。
#
# 【原因】
#   Scene_Battle 3新 在 phase3 里按需 new 了一大批子窗口 / Sprite：
#   @item_window、@help2_window、@itemicon_window、@command_window、
#   @command2_window、@back …… 而 1新 的 main 释放清单只覆盖原版就有的
#   @actor_command_window / @party_command_window / @help_window /
#   @status_window / @message_window / @skill_window / @item_window /
#   @result_window / @spriteset，上面这批新加的既不在清单里，下面这些
#   分支里也没人释放：
#
#     * 选"围攻"时直接 start_phase4，指令窗口整套留在画面上；
#     * 选"物品 → 使用/投掷"时 @command_window / @command2_window 只被
#       visible = false，之后没有任何路径 dispose；
#     * 换目标、按 B 取消、换角色、进出不同选择模式时，@help2_window /
#       @itemicon_window / @status3_window / @back 经常只隐藏不释放。
#
#   窗口对象泄漏之后依然在 mkxp 的绘制列表里，每帧照画，于是文字"残留"；
#   battle 结束 main 也不会收它们，就一路留到了地图上。
#
# 【处理】
#   1. 进入主回合（@phase >= 4）后，phase3 的选择类窗口已经全部用不上，
#      每帧兜底扫描一次，把还在的一律 visible = false + dispose + 置 nil
#      （phase4 / 结算只用 @actor_command_window、@help_window、
#      @status_window、@status7_window、@party_command_window 和 @spriteset，
#      故意不动它们）。
#   2. battle_end 时再清一次，避免 Graphics.freeze 把残留文字拍进过渡图。
#   3. main 的 ensure 兜底，任何意外中断都不会把窗口带到 Scene_Map。
#   4. 隐藏中的物品 / 技能窗口不再刷新帮助窗：Window_Help#set_text 与
#      Window_Help_Self#draw_tj_help 都会无条件 self.visible = true，
#      窗口隐藏后只要还在 update（active 一直没取消）就会把帮助文字重新
#      点亮，这是中途"点完物品冒出文字"的直接来源。
#==============================================================================

module TJ_BattleResidue
  # phase3 里按需 new 出来的窗口 / Sprite。phase4 与结算阶段一个都不用，
  # 所以进入主回合后可以整体释放。
  PHASE3_ONLY = [
    :@back,
    :@help2_window, :@help3_window,
    :@item_window, :@item2_window, :@itemzd_window, :@item4_window,
    :@itemicon_window, :@itemicon2_window,
    :@skill_window, :@touxiang_window, :@bb_window, :@status3_window,
    :@command_window, :@command2_window,
    :@right_window, :@left_window,
    :@enemy_arrow, :@actor_arrow
  ]

  # 隐藏 + 释放。dispose 前后都做异常保护，避免某个分支已经把对象释放掉时
  # 抛 "disposed" 把整帧 update 打断。
  def self.release(obj)
    return if obj.nil?
    begin
      obj.visible = false if obj.respond_to?(:visible=)
    rescue Exception
    end
    begin
      done = false
      begin
        done = obj.disposed? if obj.respond_to?(:disposed?)
      rescue Exception
        done = false
      end
      obj.dispose unless done
    rescue Exception
    end
  end

  def self.sweep(scene)
    return if scene.nil?
    PHASE3_ONLY.each do |iv|
      obj = nil
      begin
        obj = scene.instance_variable_get(iv)
      rescue Exception
        obj = nil
      end
      next if obj.nil?
      release(obj)
      begin
        scene.instance_variable_set(iv, nil)
      rescue Exception
      end
    end
  end
end

class Scene_Battle
  # ● 每帧兜底：进了主回合（@phase 4 / 5）phase3 的子窗口一律不该还在
  alias tj_residue_update update

  def update
    tj_residue_update
    TJ_BattleResidue.sweep(self) if @phase != nil and @phase >= 4
  end

  # ● 战斗结束：先清窗口再切场景，过渡图里不会带残留文字
  alias tj_residue_battle_end battle_end

  def battle_end(result)
    TJ_BattleResidue.sweep(self)
    tj_residue_battle_end(result)
  end

  # ● 兜底：main 里任何一条出口都不让窗口活到地图画面
  alias tj_residue_main main

  def main
    tj_residue_main
  ensure
    TJ_BattleResidue.sweep(self)
  end
end

#------------------------------------------------------------------------------
# 隐藏中的列表窗口不再刷新帮助窗
#
# Window_Selectablewupin#update 每帧都会调 update_help（只要 active），而
# update_help 不看 visible；帮助窗的 set_text / draw_tj_help 又无条件
# self.visible = true。于是"选中物品 → 物品窗藏起来 → 帮助窗又被点亮"，
# 在战斗里表现为点完物品冒出一行字。窗口不可见时直接跳过刷新即可：等到
# 窗口重新可见，下一帧 update 会自己补上。
#------------------------------------------------------------------------------
[:Window_Item, :Window_Item2, :Window_Skill].each do |const|
  next unless Object.const_defined?(const)
  klass = Object.const_get(const)
  next unless klass.method_defined?(:update_help)
  klass.class_eval do
    alias_method :tj_residue_update_help, :update_help

    def update_help
      return unless self.visible
      tj_residue_update_help
    end
  end
end
