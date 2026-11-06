package com.ruoyi.system.service;

import java.util.List;
import com.ruoyi.system.domain.AgentQueryBlockRule;

/**
 * 数据分析查询约束规则服务。
 */
public interface IAgentQueryBlockRuleService
{
    List<AgentQueryBlockRule> selectRuleList(AgentQueryBlockRule filter);

    int insertRule(AgentQueryBlockRule rule);

    int updateRule(AgentQueryBlockRule rule);

    int deleteRuleByIds(Long[] ids);
}
