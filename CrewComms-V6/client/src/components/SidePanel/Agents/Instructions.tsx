import React, { useState, useId } from 'react';
import { PlusCircle } from 'lucide-react';
import * as Menu from '@ariakit/react/menu';
import { DropdownPopup } from '@librechat/client';
import { specialVariables } from 'librechat-data-provider';
import { Controller, useFormContext } from 'react-hook-form';
import type { TSpecialVarLabel } from 'librechat-data-provider';
import type { AgentForm } from '~/common';
import { cn, defaultTextProps, removeFocusOutlines } from '~/utils';
import { useLocalize } from '~/hooks';
import { crewProfiles } from './crewProfiles';

const inputClass = cn(
  defaultTextProps,
  'flex w-full px-3 py-2 border-border-light bg-surface-secondary focus-visible:ring-2 focus-visible:ring-ring-primary',
  removeFocusOutlines,
);

interface VariableOption {
  label: TSpecialVarLabel;
  value: string;
}

const variableOptions: VariableOption[] = Object.keys(specialVariables).map((key) => ({
  label: `com_ui_special_var_${key}` as TSpecialVarLabel,
  value: `{{${key}}}`,
}));

export default function Instructions() {
  const menuId = useId();
  const presetsMenuId = useId();
  const localize = useLocalize();
  const profileButtonLabel = `${localize('com_ui_add')} ${localize('com_ui_role')}`;
  const methods = useFormContext<AgentForm>();
  const { control, setValue, getValues } = methods;

  const [isMenuOpen, setIsMenuOpen] = useState(false);
  const [isPresetMenuOpen, setIsPresetMenuOpen] = useState(false);

  const handleAddVariable = (label: TSpecialVarLabel, value: string) => {
    const currentInstructions = getValues('instructions') || '';
    const spacer = currentInstructions.length > 0 ? '\n' : '';
    const prefix = localize(label);
    setValue('instructions', currentInstructions + spacer + prefix + ': ' + value, {
      shouldDirty: true,
      shouldTouch: true,
    });
    setIsMenuOpen(false);
  };

  const handleApplyPreset = (preset: (typeof crewProfiles)[number]) => {
    setValue('instructions', preset.instructions, {
      shouldDirty: true,
      shouldTouch: true,
    });
    setIsPresetMenuOpen(false);
  };

  return (
    <div className="mb-4">
      <div className="mb-2 flex flex-wrap items-center gap-2">
        <label
          className="text-token-text-primary flex-grow text-sm font-medium"
          htmlFor="instructions"
        >
          {localize('com_ui_instructions')}
        </label>
        <div className="ml-auto flex flex-wrap items-center gap-2">
          <div title="Apply a role profile to instructions">
            <DropdownPopup
              portal={true}
              mountByState={true}
              unmountOnHide={true}
              preserveTabOrder={true}
              isOpen={isPresetMenuOpen}
              setIsOpen={setIsPresetMenuOpen}
              trigger={
                <Menu.MenuButton
                  id="presets-menu-button"
                  aria-label={profileButtonLabel}
                  className="flex h-7 items-center gap-1 rounded-md border border-border-medium bg-surface-secondary px-2 py-0 text-sm text-text-primary transition-colors duration-200 hover:bg-surface-tertiary"
                >
                  {profileButtonLabel}
                </Menu.MenuButton>
              }
              items={crewProfiles.map((preset) => ({
                label: preset.label,
                description: preset.description,
                onClick: () => handleApplyPreset(preset),
              }))}
              menuId={presetsMenuId}
              className="z-30"
            />
          </div>
          <div title="Add variables to instructions">
            <DropdownPopup
              portal={true}
              mountByState={true}
              unmountOnHide={true}
              preserveTabOrder={true}
              isOpen={isMenuOpen}
              setIsOpen={setIsMenuOpen}
              trigger={
                <Menu.MenuButton
                  id="variables-menu-button"
                  aria-label="Add variable to instructions"
                  className="flex h-7 items-center gap-1 rounded-md border border-border-medium bg-surface-secondary px-2 py-0 text-sm text-text-primary transition-colors duration-200 hover:bg-surface-tertiary"
                >
                  <PlusCircle className="mr-1 h-3 w-3 text-text-secondary" aria-hidden={true} />
                  {localize('com_ui_variables')}
                </Menu.MenuButton>
              }
              items={variableOptions.map((option) => ({
                label: localize(option.label) || option.label,
                onClick: () => handleAddVariable(option.label, option.value),
              }))}
              menuId={menuId}
              className="z-30"
            />
          </div>
        </div>
      </div>
      <Controller
        name="instructions"
        control={control}
        render={({ field, fieldState: { error } }) => (
          <>
            <textarea
              {...field}
              value={field.value ?? ''}
              className={cn(inputClass, 'min-h-[100px] resize-y')}
              id="instructions"
              placeholder={localize('com_agents_instructions_placeholder')}
              rows={3}
              aria-label="Agent instructions"
              aria-required="true"
              aria-invalid={error ? 'true' : 'false'}
            />
            {error && (
              <span
                className="text-sm text-red-500 transition duration-300 ease-in-out"
                role="alert"
              >
                {localize('com_ui_field_required')}
              </span>
            )}
          </>
        )}
      />
    </div>
  );
}
