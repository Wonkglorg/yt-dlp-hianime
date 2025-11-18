__version__ = "3.0.0"

import sys
import os

sys.path.append(os.path.dirname(os.path.abspath(__file__)))

import re
from yt_dlp.extractor.common import InfoExtractor
from yt_dlp.utils import ExtractorError, clean_html, get_element_by_class
from megacloud import Megacloud

class HiAnimeIE(InfoExtractor):
    _VALID_URL = r'https?://hianime(?:z)?\.(?:to|is|nz|bz|pe|cx|gs|do)/(?:watch/)?(?P<slug>[^/?]+)(?:-\d+)?-(?P<playlist_id>\d+)(?:\?ep=(?P<episode_id>\d+))?$'

    _TESTS = [
        {
            'url': 'https://hianimez.to/demon-slayer-kimetsu-no-yaiba-hashira-training-arc-19107',
            'info_dict': {
                'id': '19107',
                'title': 'Demon Slayer: Kimetsu no Yaiba Hashira Training Arc',
            },
            'playlist_count': 8,
        },
        {
            'url': 'https://hianimez.to/watch/demon-slayer-kimetsu-no-yaiba-hashira-training-arc-19107?ep=124260',
            'info_dict': {
                'id': '124260',
                'title': 'To Defeat Muzan Kibutsuji',
                'ext': 'mp4',
                'series': 'Demon Slayer: Kimetsu no Yaiba Hashira Training Arc',
                'series_id': '19107',
                'episode': 'To Defeat Muzan Kibutsuji',
                'episode_number': 1,
                'episode_id': '124260',
            },
        },
        {
            'url': 'https://hianimez.to/the-eminence-in-shadow-17473',
            'info_dict': {
                'id': '17473',
                'title': 'The Eminence in Shadow',
            },
            'playlist_count': 20,
        },
        {
            'url': 'https://hianimez.to/watch/the-eminence-in-shadow-17473?ep=94440',
            'info_dict': {
                'id': '94440',
                'title': 'The Hated Classmate',
                'ext': 'mp4',
                'series': 'The Eminence in Shadow',
                'series_id': '17473',
                'episode': 'The Hated Classmate',
                'episode_number': 1,
                'episode_id': '94440',
            },
        },
    ]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.anime_title = None
        self.episode_list = {}
        self.language = {
            'sub': 'ja',
            'dub': 'en',
            'raw': 'ja'
        }
        self.language_codes = {
            'Arabic': 'ar',
            'English Dubbed': 'en-IN',
            'English Subbed': 'en',
            'French - Francais(France)': 'fr',
            'German - Deutsch': 'de',
            'Italian - Italiano': 'it',
            'Portuguese - Portugues(Brasil)': 'pt',
            'Russian': 'ru',
            'Spanish - Espanol': 'es',
            'Spanish - Espanol(Espana)': 'es',
        }

    def _real_extract(self, url):
        mobj = self._match_valid_url(url)
        playlist_id = mobj.group('playlist_id')
        episode_id = mobj.group('episode_id')
        slug = mobj.group('slug')
        self.base_url = re.match(r'https?://[^/]+', url).group(0)

        if episode_id:
            return self._extract_episode(slug, playlist_id, episode_id)
        elif playlist_id:
            return self._extract_playlist(slug, playlist_id)
        else:
            raise ExtractorError('Unsupported URL format')

    # ========== Playlist and Episode Extraction ========== #

    # ========== Playlist Extraction ========== #

    def _extract_playlist(self, slug, playlist_id):
        anime_title = self._get_anime_title(slug, playlist_id)
        playlist_url = f'{self.base_url}/ajax/v2/episode/list/{playlist_id}'
        playlist_data = self._download_json(playlist_url, playlist_id, note='Fetching Episode List')
        episodes = self._get_elements_by_tag_and_attrib(
            playlist_data['html'], tag='a', attribute='class', value='ep-item'
        )

        entries = []
        for episode in episodes:
            html = episode.group(0)
            title = re.search(r'title="([^"]+)"', html)
            number = re.search(r'data-number="([^"]+)"', html)
            data_id = re.search(r'data-id="([^"]+)"', html)
            href = re.search(r'href="([^"]+)"', html)

            ep_id = data_id.group(1) if data_id else None
            ep_title = clean_html(title.group(1)) if title else None
            ep_number = int(number.group(1)) if number else None
            ep_url = f'{self.base_url}{href.group(1)}' if href else None

            self.episode_list[ep_id] = {
                'title': ep_title,
                'number': ep_number,
                'url': ep_url,
            }

            entries.append(self.url_result(
                ep_url,
                ie=self.ie_key(),
                video_id=ep_id,
                video_title=ep_title,
            ))

        return self.playlist_result(entries, playlist_id, anime_title)
    
    # ========== Episode Extraction ========== #

    def _extract_episode(self, slug, playlist_id, episode_id):
        anime_title = self._get_anime_title(slug, playlist_id)
        episode_language = self._get_selected_language()

        if episode_id not in self.episode_list:
            self._extract_playlist(slug, playlist_id)

        episode_data = self.episode_list.get(episode_id)

        if not episode_data:
            raise ExtractorError(f'Episode data for episode_id {episode_id} not found')

        servers_url = f'{self.base_url}/ajax/v2/episode/servers?episodeId={episode_id}'
        servers_data = self._download_json(servers_url, episode_id, note='Fetching Server IDs')

        formats = []
        subtitles = {}
        for server_type in [episode_language]:
            # Get all server items for this type
            server_items = self._get_elements_by_tag_and_attrib(
                servers_data['html'], tag='div', attribute='data-type',
                value=server_type, escape_value=False
            )

            server_items_filtered = [
                s for s in server_items
                if f'data-type="{server_type}"' in s.group(0)
            ]

            server_id = None
            working_formats = None
            working_subtitles_data = None

            # Try HD-1, HD-2, HD-3
            for n in range(1, 4):
                target_label = f"HD-{n}"

                candidate_id = None
                for s in server_items_filtered:
                    block = s.group(0)
                    if (re.search(rf'>\s*{re.escape(target_label)}\s*</a>', block)
                            and (m := re.search(r'data-id="([^"]+)"', block))):
                        candidate_id = m.group(1)
                        break

                if not candidate_id:
                    continue  # HD-n not present

                try:
                    sources_url = f'{self.base_url}/ajax/v2/episode/sources?id={candidate_id}'
                    src_json = self._download_json(
                        sources_url, episode_id,
                        note=f'Trying {server_type.upper()} {target_label}'
                    )

                    embed_url = src_json.get('link')
                    if not embed_url:
                        continue

                    scraper = Megacloud(embed_url)
                    data = scraper.extract()

                    # Collect m3u8
                    m3u8_list = [
                        s.get("file") for s in (data.get("sources", []) + data.get("sourcesBackup", []))
                        if s.get("file", "").endswith(".m3u8")
                    ]

                    if not m3u8_list:
                        continue

                    # Try each m3u8 if any invalid parts exist
                    hd_formats = None
                    for m3u8_url in m3u8_list:
                        try:
                            extracted = self._extract_custom_m3u8_formats(
                                m3u8_url,
                                episode_id,
                                headers={"Referer": "https://megacloud.blog/"},
                                server_type=server_type
                            )
                            if extracted:
                                hd_formats = extracted
                                break
                        except Exception:
                            continue

                    if not hd_formats:
                        continue

                    server_id = candidate_id
                    working_formats = hd_formats
                    working_subtitles_data = data
                    break

                except Exception:
                    continue

            if not server_id or not working_formats:
                raise ExtractorError(
                    f"[HiAnime] No {server_type.upper()} servers could be reached for episode {episode_id}",
                    expected=True
                )

            formats.extend(working_formats)

            data = working_subtitles_data
            # Extract subtitles
            for track in data.get("tracks", []):
                if track.get("kind") != "captions":
                    continue

                label = track.get("label") or ""
                file_url = track.get("file")

                if label == "English":
                    label += f' {server_type.capitalize()}bed'

                lang_code = self.language_codes.get(label, label)

                if file_url:
                    subtitles.setdefault(lang_code, []).append({
                        'name': label,
                        'url': file_url,
                    })
        return {
            'id': episode_id,
            'title': episode_data['title'],
            'formats': formats,
            'subtitles': subtitles,
            'series': anime_title,
            'series_id': playlist_id,
            'episode': episode_data['title'],
            'episode_number': episode_data['number'],
            'episode_id': episode_id,
        }

    # ========== Helpers ========== #

    def _extract_custom_m3u8_formats(self, m3u8_url, episode_id, headers, server_type=None):
        formats = self._extract_m3u8_formats(
            m3u8_url, episode_id, 'mp4', entry_protocol='m3u8_native',
            note='Downloading M3U8 Information', headers=headers
        )
        for f in formats:
            height = f.get('height')
            f['format_id'] = f'{server_type}_{height}p'
            f['language'] = self.language[server_type]
            f['http_headers'] = headers
        return formats

    # gets custom yt-dlp language parameter
    def _get_selected_language(self):
        args = self._configuration_arg('language')

        if args:
            choice = args[-1].lower()
            if choice in ('sub', 'dub', 'raw'):
                return choice

        return 'sub'

    def _get_anime_title(self, slug, playlist_id):
        if self.anime_title:
            return self.anime_title
        webpage = self._download_webpage(
            f'{self.base_url}/{slug}-{playlist_id}',
            playlist_id,
            note='Fetching Anime Title'
        )
        self.anime_title = get_element_by_class('film-name dynamic-name', webpage)
        return self.anime_title

    def _get_elements_by_tag_and_attrib(self, html, tag=None, attribute=None, value=None, escape_value=True):
        tag = tag or r'[a-zA-Z0-9:._-]+'
        if attribute:
            attribute = rf'\s+{re.escape(attribute)}'
        if value:
            value = re.escape(value) if escape_value else value
            value = f'=[\'"]?(?P<value>.*?{value}.*?)[\'"]?'

        return list(re.finditer(rf'''(?xs)
            <{tag}
            (?:\s+[a-zA-Z0-9:._-]+(?:=[a-zA-Z0-9:._-]*|="[^"]*"|='[^']*'|))*?
            {attribute}{value}
            (?:\s+[a-zA-Z0-9:._-]+(?:=[a-zA-Z0-9:._-]*|="[^"]*"|='[^']*'|))*?
            \s*>
            (?P<content>.*?)
            </{tag}>
        ''', html))