import { Selector } from "@/components";
import { useModals, withModal } from "@/modules/modals";
import { BuildKey, useSelectorOptions } from "@/utilities";
import { ASSERT } from "@/utilities/console";
import {
  Button,
  Divider,
  Group,
  Text as MantineText,
  SimpleGrid,
  Stack,
} from "@mantine/core";
import { useForm } from "@mantine/form";
import { capitalize } from "lodash";
import {
  FunctionComponent,
  forwardRef,
  useCallback,
  useMemo,
  useRef,
  useState,
} from "react";
import {
  Card,
  Check,
  Chips,
  Selector as GlobalSelector,
  Message,
  Password,
  ProviderTestButton,
  Text,
} from "../components";
import {
  FormContext,
  FormValues,
  runHooks,
  useFormActions,
  useStagedValues,
} from "../utilities/FormValues";
import { SettingsProvider, useSettings } from "../utilities/SettingsProvider";
import { useSettingValue } from "../utilities/hooks";
import { ProviderInfo } from "./list";

type SettingsKey =
  | "settings-general-enabled_providers"
  | "settings-general-enabled_integrations";

interface ProviderViewProps {
  availableOptions: Readonly<ProviderInfo[]>;
  settingsKey: SettingsKey;
}

export const ProviderView: FunctionComponent<ProviderViewProps> = ({
  availableOptions,
  settingsKey,
}) => {
  const settings = useSettings();
  const staged = useStagedValues();
  const providers = useSettingValue<string[]>(settingsKey);

  const { update } = useFormActions();

  const modals = useModals();

  const select = useCallback(
    (v?: ProviderInfo) => {
      if (settings) {
        modals.openContextModal(ProviderModal, {
          payload: v ?? null,
          enabledProviders: providers ?? [],
          staged,
          settings,
          onChange: update,
          availableOptions: availableOptions,
          settingsKey: settingsKey,
        });
      }
    },
    [
      modals,
      providers,
      settings,
      staged,
      update,
      availableOptions,
      settingsKey,
    ],
  );

  const cards = useMemo(() => {
    if (providers) {
      return providers
        .flatMap((v) => {
          const item = availableOptions.find((inn) => inn.key === v);
          if (item) {
            return item;
          } else {
            return [];
          }
        })
        .map((v, idx) => (
          <Card
            key={BuildKey(v.key, idx)}
            header={v.name ?? capitalize(v.key)}
            description={v.description}
            onClick={() => select(v)}
          ></Card>
        ));
    } else {
      return [];
    }
  }, [providers, select, availableOptions]);

  return (
    <SimpleGrid cols={3}>
      {cards}
      <Card plus onClick={() => select()}></Card>
    </SimpleGrid>
  );
};

interface ProviderToolProps {
  payload: ProviderInfo | null;
  // TODO: Find a better solution to pass this info to modal
  enabledProviders: readonly string[];
  staged: LooseObject;
  settings: Settings;
  onChange: (v: LooseObject) => void;
  availableOptions: Readonly<ProviderInfo[]>;
  settingsKey: Readonly<SettingsKey>;
}

const SelectItem = forwardRef<
  HTMLDivElement,
  { payload: ProviderInfo; label: string }
>(({ payload: { description }, label, ...other }, ref) => {
  return (
    <Stack spacing={1} ref={ref} {...other}>
      <MantineText size="md">{label}</MantineText>
      <MantineText size="xs">{description}</MantineText>
    </Stack>
  );
});

const ProviderTool: FunctionComponent<ProviderToolProps> = ({
  payload,
  enabledProviders,
  staged,
  settings,
  onChange,
  availableOptions,
  settingsKey,
}) => {
  const modals = useModals();

  const onChangeRef = useRef(onChange);
  onChangeRef.current = onChange;

  const [info, setInfo] = useState<Nullable<ProviderInfo>>(payload);

  const form = useForm<FormValues>({
    initialValues: {
      settings: staged,
      hooks: {},
    },
  });

  const deletePayload = useCallback(() => {
    if (payload && enabledProviders) {
      const idx = enabledProviders.findIndex((v) => v === payload.key);
      if (idx !== -1) {
        const newProviders = [...enabledProviders];
        newProviders.splice(idx, 1);
        onChangeRef.current({ [settingsKey]: newProviders });
        modals.closeAll();
      }
    }
  }, [payload, enabledProviders, modals, settingsKey]);

  const submit = useCallback(
    (values: FormValues) => {
      if (info && enabledProviders) {
        const changes = { ...values.settings };
        const hooks = values.hooks;

        // Add this provider if not exist
        if (enabledProviders.find((v) => v === info.key) === undefined) {
          changes[settingsKey] = [...enabledProviders, info.key];
        }

        // Apply submit hooks
        runHooks(hooks, changes);

        onChangeRef.current(changes);
        modals.closeAll();
      }
    },
    [info, enabledProviders, modals, settingsKey],
  );

  const canSave = info !== null;

  const onSelect = useCallback((item: Nullable<ProviderInfo>) => {
    if (item) {
      setInfo(item);
    } else {
      setInfo({
        key: "",
        description: "Unknown Provider",
      });
    }
  }, []);

  const options = useMemo(
    () =>
      availableOptions.filter(
        (v) =>
          enabledProviders?.find((p) => p === v.key && p !== info?.key) ===
          undefined,
      ),
    [info?.key, enabledProviders, availableOptions],
  );

  const selectorOptions = useSelectorOptions(
    options,
    (v) => v.name ?? capitalize(v.key),
  );

  const inputs = useMemo(() => {
    if (info === null || info.inputs === undefined) {
      return null;
    }

    const itemKey = info.key;

    const elements: JSX.Element[] = [];

    info.inputs?.forEach((value) => {
      const key = value.key;
      const label = value.name ?? capitalize(value.key);
      const options = value.options ?? [];

      switch (value.type) {
        case "text":
          elements.push(
            <Text
              key={BuildKey(itemKey, key)}
              label={label}
              settingKey={`settings-${itemKey}-${key}`}
            ></Text>,
          );
          return;
        case "password":
          elements.push(
            <Password
              key={BuildKey(itemKey, key)}
              label={label}
              settingKey={`settings-${itemKey}-${key}`}
            ></Password>,
          );
          return;
        case "switch":
          elements.push(
            <Check
              key={key}
              inline
              label={label}
              settingKey={`settings-${itemKey}-${key}`}
            ></Check>,
          );
          return;
        case "select":
          elements.push(
            <GlobalSelector
              key={key}
              label={label}
              settingKey={`settings-${itemKey}-${key}`}
              options={options}
            ></GlobalSelector>,
          );
          return;
        case "testbutton":
          elements.push(
            <ProviderTestButton category={key}></ProviderTestButton>,
          );
          return;
        case "chips":
          elements.push(
            <Chips
              key={key}
              label={label}
              settingKey={`settings-${itemKey}-${key}`}
            ></Chips>,
          );
          return;
        default:
          ASSERT(false, "Implement your new input here");
      }
    });

    return <Stack spacing="xs">{elements}</Stack>;
  }, [info]);

  return (
    <SettingsProvider value={settings}>
      <FormContext.Provider value={form}>
        <Stack>
          <Stack spacing="xs">
            <Selector
              data-autofocus
              searchable
              placeholder="Click to Select a Provider"
              itemComponent={SelectItem}
              disabled={payload !== null}
              {...selectorOptions}
              value={info}
              onChange={onSelect}
            ></Selector>
            <Message>{info?.description}</Message>
            {inputs}
            <div hidden={info?.message === undefined}>
              <Message>{info?.message}</Message>
            </div>
          </Stack>
          <Divider></Divider>
          <Group position="right">
            <Button hidden={!payload} color="red" onClick={deletePayload}>
              Delete
            </Button>
            <Button
              disabled={!canSave}
              onClick={() => {
                submit(form.values);
              }}
            >
              Save
            </Button>
          </Group>
        </Stack>
      </FormContext.Provider>
    </SettingsProvider>
  );
};

const ProviderModal = withModal(ProviderTool, "provider-tool", {
  title: "Provider",
  size: "calc(50vw)",
});
