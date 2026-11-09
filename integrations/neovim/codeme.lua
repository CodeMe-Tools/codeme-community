-- Codeme Neovim Integration
-- Thin-client plugin for syntax check, quality verification, and deterministic repair

local M = {}

M.setup = function(opts)
  opts = opts or {}
  local auto_fix = opts.auto_fix_on_save or false

  -- Configure errorformat to recognize Codeme CDM diagnostics
  vim.o.errorformat = [=[[%[CDM-%*[A-Z0-9-]%*]] %f:%l:%c: %m]=]

  -- User commands
  vim.api.nvim_create_user_command("CodemeCheck", function()
    local file = vim.fn.expand("%:p")
    vim.cmd("silent make! run --file " .. vim.fn.fnameescape(file))
    vim.cmd("copen")
  end, { desc = "Run Codeme syntax check on current file" })

  vim.api.nvim_create_user_command("CodemeFix", function()
    local file = vim.fn.expand("%:p")
    vim.fn.system("codeme-syntax run --fix --file " .. vim.fn.fnameescape(file))
    vim.cmd("edit!")
  end, { desc = "Apply deterministic Codeme fix on current file" })

  vim.api.nvim_create_user_command("CodemeFixLoop", function()
    local dir = vim.fn.getcwd()
    vim.fn.system("codeme-skills fix-loop --repo " .. vim.fn.fnameescape(dir))
    vim.cmd("checktime")
  end, { desc = "Run full Codeme deterministic fix loop on repository" })

  -- Optional save-time auto repair
  if auto_fix then
    vim.api.nvim_create_autocmd("BufWritePre", {
      pattern = { "*.py", "*.js", "*.ts", "*.swift" },
      callback = function()
        local file = vim.fn.expand("%:p")
        vim.fn.system("codeme-syntax run --fix --file " .. vim.fn.fnameescape(file))
      end,
    })
  end
end

return M
