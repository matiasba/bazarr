import {
  badgeUpdateAll,
  bootstrap,
  movieDeleteItems,
  movieUpdateList,
  seriesDeleteItems,
  seriesUpdateList,
  siteAddNotifications,
  siteInitializationFailed,
  siteUpdateOffline,
  systemUpdateLanguagesAll,
  systemUpdateSettings,
} from "../@redux/actions";
import reduxStore from "../@redux/store";

function bindToReduxStore(fn: (ids?: number[]) => any): SocketIO.ActionFn {
  return (ids?: number[]) => reduxStore.dispatch(fn(ids));
}

export function createDefaultReducer(): SocketIO.Reducer[] {
  return [
    {
      key: "connect",
      any: () => reduxStore.dispatch(siteUpdateOffline(false)),
    },
    {
      key: "connect",
      any: () => reduxStore.dispatch<any>(bootstrap()),
    },
    {
      key: "connect_error",
      any: () => {
        const initialized = reduxStore.getState().site.initialized;
        if (initialized === true) {
          reduxStore.dispatch(siteUpdateOffline(true));
        } else {
          reduxStore.dispatch(siteInitializationFailed());
        }
      },
    },
    {
      key: "disconnect",
      any: () => reduxStore.dispatch(siteUpdateOffline(true)),
    },
    {
      key: "message",
      update: (msg?: string[]) => {
        if (msg) {
          const notifications = msg.map<ReduxStore.Notification>((message) => ({
            message,
            type: "info",
            id: "backend-message",
            timeout: 5 * 1000,
          }));

          reduxStore.dispatch(siteAddNotifications(notifications));
        }
      },
    },
    {
      key: "series",
      update: bindToReduxStore(seriesUpdateList),
      delete: bindToReduxStore(seriesDeleteItems),
    },
    {
      key: "movie",
      update: bindToReduxStore(movieUpdateList),
      delete: bindToReduxStore(movieDeleteItems),
    },
    {
      key: "settings",
      any: bindToReduxStore(systemUpdateSettings),
    },
    {
      key: "languages",
      any: bindToReduxStore(systemUpdateLanguagesAll),
    },
    {
      key: "badges",
      any: bindToReduxStore(badgeUpdateAll),
    },
  ];
}