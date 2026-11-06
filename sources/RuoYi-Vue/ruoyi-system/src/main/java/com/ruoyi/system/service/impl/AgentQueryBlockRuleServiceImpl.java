package com.ruoyi.system.service.impl;

import java.util.List;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.dao.DuplicateKeyException;
import org.springframework.stereotype.Service;
import com.ruoyi.common.constant.HttpStatus;
import com.ruoyi.common.exception.ServiceException;
import com.ruoyi.system.domain.AgentQueryBlockRule;
import com.ruoyi.system.mapper.AgentQueryBlockRuleMapper;
import com.ruoyi.system.service.IAgentQueryBlockRuleService;

/**
 * 数据分析查询约束规则服务实现。
 */
@Service
public class AgentQueryBlockRuleServiceImpl implements IAgentQueryBlockRuleService
{
    @Autowired
    private AgentQueryBlockRuleMapper ruleMapper;

    @Override
    public List<AgentQueryBlockRule> selectRuleList(AgentQueryBlockRule filter)
    {
        return ruleMapper.selectRuleList(filter);
    }

    @Override
    public int insertRule(AgentQueryBlockRule rule)
    {
        try
        {
            return ruleMapper.insertRule(rule);
        }
        catch (DuplicateKeyException e)
        {
            throw new ServiceException("相同的数据库、表和字段约束规则已存在", HttpStatus.CONFLICT);
        }
    }

    @Override
    public int updateRule(AgentQueryBlockRule rule)
    {
        try
        {
            return ruleMapper.updateRule(rule);
        }
        catch (DuplicateKeyException e)
        {
            throw new ServiceException("相同的数据库、表和字段约束规则已存在", HttpStatus.CONFLICT);
        }
    }

    @Override
    public int deleteRuleByIds(Long[] ids)
    {
        return ruleMapper.deleteRuleByIds(ids);
    }
}
