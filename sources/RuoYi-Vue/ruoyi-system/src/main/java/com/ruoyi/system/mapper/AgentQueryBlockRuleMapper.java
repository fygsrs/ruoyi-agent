package com.ruoyi.system.mapper;

import java.util.List;
import com.ruoyi.system.domain.AgentQueryBlockRule;

/**
 * 数据分析查询约束规则数据层。
 */
public interface AgentQueryBlockRuleMapper
{
    List<AgentQueryBlockRule> selectRuleList(AgentQueryBlockRule filter);

    int insertRule(AgentQueryBlockRule rule);

    int updateRule(AgentQueryBlockRule rule);

    int deleteRuleByIds(Long[] ids);
}
