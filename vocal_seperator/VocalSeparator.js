import ffmpeg from "fluent-ffmpeg";
import ffmpegPath from "ffmpeg-static";
import inquirer from 'inquirer';
import path from 'path';
import chalk from 'chalk';
import fs from 'fs';
import { fileURLToPath } from "url";
import { dirname } from "path";

ffmpeg.setFfmpegPath(ffmpegPath);
const __filename = fileURLToPath(import.meta.url);
const __dirname = dirname(__filename);

const groups = {
    ITZY: ['Yeji', 'Lia', 'Ryujin', 'Chaeryeong', 'Yuna'],
    IVE: ['Gaeul', 'Yujin', 'Rei', 'Wonyoung', 'Liz', 'Leeseo']
};

const removeSilence = (inputPath, outputPath) => {
    ffmpeg(inputPath)
      .audioFilters('silenceremove=stop_periods=-1:stop_duration=1:stop_threshold=-50dB')
      .output(outputPath)
      .on('end', () => {
        console.log(chalk.green('Silence removed and saved to:', outputPath));
      })
      .on('error', (err) => {
        console.error(chalk.red('Error occurred:', err.message));
      })
      .run();
  };

const main = async () => {
    //Choose a group
    const { selectedGroup } = await inquirer.prompt([
        {
            type: 'list',
            name: 'selectedGroup',
            message: 'Choose a group:',
            choices: Object.keys(groups)
        }
    ]);

    //Chose member from selectedGroup
    const { selectedMember } = await inquirer.prompt([
        {
            type: 'list',
            name: 'selectedMember',
            message: `Choose a member from ${selectedGroup}`,
            choices: groups[selectedGroup]
        }
    ]);

    const directoryPath = path.join(__dirname, `../${selectedGroup}/${selectedMember}/train`);

    if (!fs.existsSync(directoryPath)) {
        console.log(chalk.red(`Warning: Directory does not exist: ${directoryPath}`));
        return;
    }

    const songs = fs.readdirSync(directoryPath).filter(file => file.endsWith('.mp3') && !file.includes('Instrumental'));

    if (songs.length === 0) {
        console.log(chalk.red('No songs found in the directory.'));
        return;
    }

    const { selectedSong } = await inquirer.prompt([
        {
            type: 'list',
            name: 'selectedSong',
            message: 'Choose a song to isolate vocals:',
            choices: songs
        }
    ]);

    const originalPath = path.join(directoryPath, selectedSong);

    const outputDirectory = path.join(directoryPath, '/Isolated_Vocals');
    //console.log(`Output dir: ${outputDirectory}`);  
    if (!fs.existsSync(outputDirectory)) {
        fs.mkdirSync(outputDirectory);
    }

    const outputPath = path.join(outputDirectory, `${selectedSong.replace('.mp3', '_Isolated_Vocals.mp3')}`);
    removeSilence(originalPath, outputPath);
}

main();